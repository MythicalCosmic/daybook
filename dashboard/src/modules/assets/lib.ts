/** Pure helpers of the fixed assets pages: tones, icons, the schedule's chart and year groups. */
import {
  AirVent,
  AppWindow,
  Armchair,
  ArrowRightLeft,
  BadgeCheck,
  Box,
  Building2,
  Car,
  Cctv,
  CirclePause,
  CirclePlay,
  ClipboardCheck,
  Gauge,
  HandHelping,
  KeyRound,
  Monitor,
  PackageCheck,
  PackageMinus,
  PackagePlus,
  PaintRoller,
  Refrigerator,
  ScanBarcode,
  Sparkles,
  StickyNote,
  Thermometer,
  TrendingDown,
  TriangleAlert,
  Undo2,
  Wrench,
} from "@lucide/vue";
import type { Component } from "vue";

import type { StatusTone } from "@/components/StatusPill.vue";

import type { AssetStatus, EventKind, ScheduleMonth, UpkeepKind } from "./types";

export const STATUS_TONES: Record<AssetStatus, StatusTone> = {
  in_use: "success",
  in_storage: "neutral",
  repair: "warning",
  suspended: "info",
  disposed: "neutral",
};

const CATEGORY_ICONS: Record<string, Component> = {
  refrigerator: Refrigerator,
  "air-vent": AirVent,
  armchair: Armchair,
  monitor: Monitor,
  "scan-barcode": ScanBarcode,
  thermometer: Thermometer,
  cctv: Cctv,
  car: Car,
  "paint-roller": PaintRoller,
  "building-2": Building2,
  "app-window": AppWindow,
  "key-round": KeyRound,
};

/** The category's icon (a lucide name from the API), a box when unknown. */
export function categoryIcon(name: string | null | undefined): Component {
  return (name && CATEGORY_ICONS[name]) || Box;
}

export const EVENT_ICONS: Record<EventKind, Component> = {
  created: PackagePlus,
  in_service: CirclePlay,
  moved: ArrowRightLeft,
  issued: HandHelping,
  returned: Undo2,
  repair: Wrench,
  service: Sparkles,
  verification: BadgeCheck,
  addition: PackagePlus,
  impairment: TrendingDown,
  estimate: Gauge,
  suspended: CirclePause,
  resumed: CirclePlay,
  usage: Gauge,
  problem: TriangleAlert,
  counted: ClipboardCheck,
  disposed: PackageMinus,
  note: StickyNote,
};

export const EVENT_TONES: Partial<Record<EventKind, StatusTone>> = {
  repair: "warning",
  problem: "warning",
  impairment: "danger",
  disposed: "neutral",
  verification: "success",
  service: "success",
  counted: "success",
  issued: "primary",
};

export const UPKEEP_ICONS: Record<UpkeepKind, Component> = {
  service: Wrench,
  verification: BadgeCheck,
  warranty: PackageCheck,
  insurance: ClipboardCheck,
};

/** Whole days from `today` to `day` (both YYYY-MM-DD): negative when it has passed. */
export function daysUntil(day: string, today: string): number {
  const ms = Date.parse(`${day}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`);
  return Math.round(ms / 86_400_000);
}

export function upkeepTone(day: string, today: string, soonDays = 30): StatusTone {
  const days = daysUntil(day, today);
  if (days < 0) return "danger";
  if (days <= soonDays) return "warning";
  return "neutral";
}

/** "2026-11-01" → "2026-11" (chart categories, the line-chart's month axis). */
export function monthKey(month: string): string {
  return month.slice(0, 7);
}

/** The book value over the asset's life: what is posted as a solid line, what lies ahead
 * dashed, both ending at the residual value. */
export function bookValueSeries(schedule: ScheduleMonth[]): { categories: string[]; posted: (string | null)[]; planned: (string | null)[] } {
  const categories = schedule.map((row) => monthKey(row.month));
  const lastPosted = schedule.reduce((index, row, at) => (row.state === "planned" ? index : at), -1);
  const posted = schedule.map((row, at) => (at <= lastPosted ? row.closing : null));
  // The planned line starts where the posted one ends, so the two meet.
  const planned = schedule.map((row, at) => (at >= Math.max(lastPosted, 0) && (row.state === "planned" || at === lastPosted) ? row.closing : null));
  return { categories, posted, planned };
}

export interface YearGroup {
  year: number;
  months: ScheduleMonth[];
  total: number;
  closing: string;
  planned: boolean;
}

/** The schedule by year: each year's months, their total and the book value it ends at. */
export function yearsOf(schedule: ScheduleMonth[]): YearGroup[] {
  const years = new Map<number, YearGroup>();
  for (const row of schedule) {
    const year = Number(row.month.slice(0, 4));
    const group = years.get(year) ?? { year, months: [], total: 0, closing: row.closing, planned: true };
    group.months.push(row);
    group.total += Number(row.amount);
    group.closing = row.closing;
    group.planned = group.planned && row.state === "planned";
    years.set(year, group);
  }
  return [...years.values()];
}

/** Sum of decimal strings as a number (for display only; the server's totals are the truth). */
export function sumMoney(values: Array<string | null | undefined>): number {
  return values.reduce((total, value) => total + (value ? Number(value) : 0), 0);
}
