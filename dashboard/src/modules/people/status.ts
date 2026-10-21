/**
 * What a person's status chip says, from their membership status, today's attendance (package F's
 * person field), approved time off today (time off's person field) and a suspension.
 */
import type { StatusTone } from "@/components/StatusPill.vue";
import type { AvatarStatus } from "@/components/UserAvatar.vue";
import { addDays, diffDays } from "@/lib/dates";

import type { Person } from "./types";

export interface StatusChip {
  tone: StatusTone;
  /** i18n key under people.status.* */
  key: string;
  params?: Record<string, string>;
  live?: boolean;
  avatar?: AvatarStatus;
}

export function statusChip(person: Pick<Person, "status" | "suspended_until" | "fields">, day: (value: string) => string): StatusChip {
  switch (person.status) {
    case "suspended":
      return person.suspended_until
        ? { tone: "warning", key: "people.status.suspendedUntil", params: { date: day(person.suspended_until) }, avatar: "away" }
        : { tone: "warning", key: "people.status.suspended", avatar: "away" };
    case "left":
      return { tone: "neutral", key: "people.status.left" };
    case "blocked":
      return { tone: "danger", key: "people.status.blocked" };
    case "pending":
      return { tone: "info", key: "people.status.pending" };
    case "rejected":
      return { tone: "neutral", key: "people.status.rejected" };
    default:
      break;
  }
  const leave = person.fields?.time_off_today;
  if (leave) return { tone: "info", key: "people.status.onLeave", params: { date: day(leave.until) }, avatar: "off" };
  switch (person.fields?.attendance_today) {
    case "in":
      return { tone: "success", key: "people.status.in", live: true, avatar: "in" };
    case "late":
      return { tone: "warning", key: "people.status.late", avatar: "late" };
    case "not_yet":
      return { tone: "neutral", key: "people.status.notYet" };
    case "absent":
      return { tone: "danger", key: "people.status.absent" };
    case "off":
      return { tone: "neutral", key: "people.status.dayOff", avatar: "off" };
    default:
      return { tone: "success", key: "people.status.active" };
  }
}

/** On-time rate tone: green from 90 %, ochre from 75 %, brick below. */
export function rateTone(rate: string | number | null | undefined): "success" | "warning" | "danger" | "neutral" {
  if (rate === null || rate === undefined || rate === "") return "neutral";
  const value = Number(rate);
  if (value >= 90) return "success";
  if (value >= 75) return "warning";
  return "danger";
}

/** "1 year 3 months", "5 months", "12 days" through the module's plural messages. */
export function tenureParts(days: number | null | undefined): { years: number; months: number; days: number } | null {
  if (days === null || days === undefined) return null;
  const years = Math.floor(days / 365);
  const months = Math.floor((days % 365) / 30);
  return { years, months, days };
}

/**
 * Approved time off still ahead (calendar days after `today`), shown next to "days off taken this
 * year", which counts up to today: together they make what the Time off tab calls approved.
 */
export function bookedDaysAhead(upcoming: ReadonlyArray<{ first_day: string; last_day: string; status: string }>, today: string): number {
  let days = 0;
  for (const item of upcoming) {
    if (item.status !== "approved" || item.last_day <= today) continue;
    const from = item.first_day > today ? item.first_day : addDays(today, 1);
    days += diffDays(from, item.last_day) + 1;
  }
  return days;
}
