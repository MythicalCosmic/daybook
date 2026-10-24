/** Colors, icons and words for task statuses, priorities and deadlines, shared by every view. */
import { TZDate } from "@date-fns/tz";
import { CalendarClock, CircleCheck, CircleDashed, CircleDot, CircleSlash, Hourglass, RotateCcw } from "@lucide/vue";
import type { Component } from "vue";

import type { StatusTone } from "@/components/StatusPill.vue";

import type { BoardColumnId, TaskKind, TaskPriority, TaskStatus } from "./types";

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

/** Only Urgent is coloured (red, with its word); High is a plain flag, as in the app and the bot. */
export const PRIORITY_TONE: Record<TaskPriority, StatusTone> = {
  urgent: "danger",
  high: "neutral",
  normal: "neutral",
  low: "neutral",
};

export const DUE_ICON = CalendarClock;

/**
 * How cards stand in an open column (To do, In progress, Sent back), the order the app and the bot
 * use too: late first, then urgent, then the server's order (by deadline). Waiting and Done keep
 * the server's order.
 */
export function boardOrder<T extends { status: TaskStatus; is_overdue: boolean; priority: TaskPriority }>(items: T[]): T[] {
  const rank = (task: T) => (task.status === "review" || task.status === "done" ? 2 : task.is_overdue ? 0 : task.priority === "urgent" ? 1 : 2);
  return items
    .map((item, index) => ({ item, index }))
    .sort((a, b) => rank(a.item) - rank(b.item) || a.index - b.index)
    .map(({ item }) => item);
}

/**
 * Given work its person hasn't opened yet (contract 10): assigned work still to do or sent back,
 * with `seen_at` null. Done, started or routine work without it isn't "unseen" (finished from a
 * reminder's button, or from before "seen" existed), nor is a row from a backend without the field.
 */
export function isUnseen(task: { kind: TaskKind; status: TaskStatus; seen_at?: string | null }): boolean {
  return task.kind === "assigned" && task.seen_at === null && (task.status === "todo" || task.status === "returned");
}

/** A board card's key as the project board and the bot write it ("OPEN-14"; "OPEN" until numbered). */
export function cardKey(project: { key: string; number?: number | null }): string {
  return project.number ? `${project.key}-${project.number}` : project.key;
}

/** Minutes between two instants (positive when `later` is after `earlier`). */
export function minutesBetween(earlier: string | Date, later: string | Date): number {
  return Math.round((new Date(later).getTime() - new Date(earlier).getTime()) / 60_000);
}

/**
 * How far behind the next reminder is, in minutes: negative while it's still ahead. A few minutes
 * is the reminder run's own rhythm; much more means the reminders have stopped.
 */
export function reminderLag(nextAt: string, now: Date): number {
  return Math.round((now.getTime() - new Date(nextAt).getTime()) / 60_000);
}

/**
 * A comment's text in pieces, with "@Name" marked wherever Name is someone the task knows
 * (longest names first, so "@Ali Valiyev" wins over "@Ali").
 */
export function highlightMentions(text: string, names: string[]): Array<{ text: string; mention: boolean }> {
  const unique = [...new Set(names.map((name) => name.trim()).filter(Boolean))].sort((a, b) => b.length - a.length);
  if (!unique.length || !text.includes("@")) return [{ text, mention: false }];
  const pattern = new RegExp(`@(?:${unique.map((name) => name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gu");
  const parts: Array<{ text: string; mention: boolean }> = [];
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    const start = match.index ?? 0;
    if (start > last) parts.push({ text: text.slice(last, start), mention: false });
    parts.push({ text: match[0], mention: true });
    last = start + match[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last), mention: false });
  return parts;
}

/** "2 h 10 min", "45 min", "3 d" for a lateness in minutes. */
export function lateness(minutes: number, words: { min: string; h: string; d: string }): string {
  const value = Math.max(0, minutes);
  if (value < 60) return `${value} ${words.min}`;
  // Past the first hour, whole hours read faster (and fit a table cell in every language) than
  // "1 h 53 min"; the exact deadline is on hover and in the drawer.
  const hours = Math.round(value / 60);
  if (hours < 24) return `${hours} ${words.h}`;
  return `${Math.max(1, Math.floor(value / 60 / 24))} ${words.d}`;
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
