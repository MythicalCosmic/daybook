/**
 * Plain helpers for the attendance screens: the geofence check the card runs before it sends a
 * tap, durations, the month grid and how a shift reads in a row.
 */
import { distanceMeters, type LocationFix } from "../../lib/location";
import { addDays, dayMonth, weekdayShort, type DayKey } from "../../lib/time";
import type { BranchGeo, CellCode, Shift } from "./types";

export type FenceCheck = { distance: number; outside: boolean };

/**
 * How far the fix is from the branch and whether that is outside its geofence, judged like the
 * server does: farther than the fence plus the reading's accuracy (at most the fence again).
 * Null when the branch has no position to compare with.
 */
export function fenceCheck(branch: BranchGeo | null, fix: Pick<LocationFix, "latitude" | "longitude" | "accuracy">): FenceCheck | null {
  if (!branch || branch.latitude === null || branch.longitude === null) return null;
  const latitude = Number(branch.latitude);
  const longitude = Number(branch.longitude);
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return null;
  const distance = distanceMeters({ latitude, longitude }, fix);
  const allowance = Math.min(Math.round(fix.accuracy ?? 0), branch.geofence_m);
  return { distance, outside: distance > branch.geofence_m + allowance };
}

/** Whole minutes from `from` to `to` (never negative). */
export function minutesBetween(from: string | Date, to: string | Date): number {
  return Math.max(0, Math.floor((new Date(to).getTime() - new Date(from).getTime()) / 60_000));
}

/** Hours and minutes of a duration, for the "{h} h {m} min" style messages. */
export function hoursMinutes(minutes: number): { h: number; m: number } {
  const total = Math.max(0, Math.round(minutes));
  return { h: Math.floor(total / 60), m: total % 60 };
}

/** "2026-10" → the first day "2026-10-01". */
export function monthStart(month: string): DayKey {
  return `${month.slice(0, 7)}-01`;
}

/** The month before or after "2026-10" ("2026-09", "2026-11"). */
export function shiftMonth(month: string, by: number): string {
  const [year, number] = month.split("-").map(Number);
  const date = new Date(Date.UTC(year, number - 1 + by, 1));
  return date.toISOString().slice(0, 7);
}

/** Monday-first weekday of a day key: 0 = Monday … 6 = Sunday. */
export function mondayIndex(day: DayKey): number {
  const [year, month, date] = day.split("-").map(Number);
  return (new Date(Date.UTC(year, month - 1, date)).getUTCDay() + 6) % 7;
}

/**
 * The weeks of a month as rows of seven day keys, Monday first; days outside the month are
 * null so the grid keeps its shape.
 */
export function monthWeeks(month: string): (DayKey | null)[][] {
  const first = monthStart(month);
  const weeks: (DayKey | null)[][] = [];
  let week: (DayKey | null)[] = Array.from({ length: mondayIndex(first) }, () => null);
  for (let day = first; day.slice(0, 7) === month.slice(0, 7); day = addDays(day, 1)) {
    week.push(day);
    if (week.length === 7) {
      weeks.push(week);
      week = [];
    }
  }
  if (week.length) weeks.push([...week, ...Array.from({ length: 7 - week.length }, () => null)]);
  return weeks;
}

/** Seven Monday-first day keys of any week, for the weekday header. */
export function weekOf(day: DayKey): DayKey[] {
  const monday = addDays(day, -mondayIndex(day));
  return Array.from({ length: 7 }, (_, index) => addDays(monday, index));
}

/** Codes a person can ask to have fixed: the past days that went wrong or look off. */
export const FIXABLE: ReadonlySet<CellCode> = new Set(["absent", "late", "auto", "present", "unscheduled", "off"]);

/** "Thu, 23 Oct" for a shift's day (its wall-clock day, whatever the phone's zone). */
export function shiftDay(shift: Pick<Shift, "starts_at">, timeZone: string, locale: string): string {
  return `${weekdayShort(shift.starts_at, timeZone, locale)}, ${dayMonth(shift.starts_at, timeZone, locale)}`;
}

/** "09:00–18:00". */
export function shiftHours(shift: Pick<Shift, "start" | "end">): string {
  return `${shift.start}–${shift.end}`;
}

/** "09:00–18:00 · Chilonzor". */
export function shiftLine(shift: Pick<Shift, "start" | "end" | "branch">): string {
  return shift.branch ? `${shiftHours(shift)} · ${shift.branch.name}` : shiftHours(shift);
}

/** "HH:MM" of an ISO time as the company's clock shows it (the ISO already carries its offset). */
export function wallClock(iso: string): string {
  return iso.slice(11, 16);
}
