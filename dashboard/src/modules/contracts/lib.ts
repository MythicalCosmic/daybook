/** Small pure helpers of the contracts screens: tones, icons, days and the term's progress. */
import { BadgeCheck, Building2, FileText, ShieldCheck, Sparkles, Truck } from "@lucide/vue";
import type { Component } from "vue";

import type { StatusTone } from "@/components/StatusPill.vue";

import type { ContractKind, ContractRow, ContractStatus } from "./types";

export const STATUS_TONES: Record<ContractStatus, StatusTone> = {
  draft: "neutral",
  active: "success",
  ending: "warning",
  ended: "neutral",
  terminated: "danger",
};

export const KIND_ICONS: Record<ContractKind, Component> = {
  lease: Building2,
  supply: Truck,
  service: Sparkles,
  licence: BadgeCheck,
  insurance: ShieldCheck,
  other: FileText,
};

/** Soft tile colours of a kind (tokens, both themes). */
export const KIND_TILES: Record<ContractKind, string> = {
  lease: "bg-accent-soft text-accent-fg",
  supply: "bg-info-soft text-info",
  service: "bg-success-soft text-success",
  licence: "bg-warning-soft text-warning",
  insurance: "bg-primary-soft text-primary",
  other: "bg-surface-2 text-muted",
};

const DAY = 86_400_000;

function utc(day: string): number {
  const [year, month, date] = day.split("-").map(Number) as [number, number, number];
  return Date.UTC(year, month - 1, date);
}

/** Whole days from `today` to `day` (negative once it has passed). */
export function daysUntil(day: string, today: string): number {
  return Math.round((utc(day) - utc(today)) / DAY);
}

/** `day` moved by `days` ("YYYY-MM-DD"). */
export function addDays(day: string, days: number): string {
  return new Date(utc(day) + days * DAY).toISOString().slice(0, 10);
}

/** The notice deadline the form previews: `notice` days before the end. */
export function noticeDeadline(endsOn: string | null, notice: number | null, autoRenews: boolean): string | null {
  if (!autoRenews || !endsOn || notice === null) return null;
  return addDays(endsOn, -notice);
}

/** How far through its term a contract is today, 0–100 (null without both dates). */
export function termProgress(startsOn: string | null, endsOn: string | null, today: string): number | null {
  if (!startsOn || !endsOn) return null;
  const span = utc(endsOn) - utc(startsOn);
  if (span <= 0) return 100;
  return Math.max(0, Math.min(100, ((utc(today) - utc(startsOn)) / span) * 100));
}

/** Where `day` sits on the term, 0–100 (null outside it or without both dates). */
export function termPosition(startsOn: string | null, endsOn: string | null, day: string | null): number | null {
  if (!startsOn || !endsOn || !day) return null;
  const span = utc(endsOn) - utc(startsOn);
  if (span <= 0) return null;
  const at = ((utc(day) - utc(startsOn)) / span) * 100;
  return at < 0 || at > 100 ? null : at;
}

/** The tone of the days-left pill: past red, within the warning amber, else calm. */
export function dayTone(row: Pick<ContractRow, "status" | "days_left" | "attention">): StatusTone {
  if (row.status === "ended" || row.status === "terminated") return "neutral";
  if (row.days_left !== null && row.days_left < 0) return "danger";
  if (row.attention) return row.days_left !== null && row.days_left <= 7 ? "danger" : "warning";
  return "neutral";
}

/** Rows that need a look first, then by their next date, then by name. */
export function byAttention(rows: ContractRow[]): ContractRow[] {
  const far = "9999-12-31";
  return [...rows].sort((a, b) => Number(!a.attention) - Number(!b.attention) || (a.key_day ?? far).localeCompare(b.key_day ?? far) || a.title.localeCompare(b.title));
}
