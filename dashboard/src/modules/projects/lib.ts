/**
 * Small pure helpers shared by the projects pages: palette colours as CSS variables, tones for
 * status and health, due-date chips, durations and board positions. Kept free of components so
 * they can be tested and reused by the widgets.
 */
import type { Component } from "vue";
import {
  Backpack,
  Building2,
  ClipboardList,
  FolderKanban,
  Globe,
  Hammer,
  Megaphone,
  Package,
  Rocket,
  ShoppingCart,
  Sparkles,
  Store,
  Truck,
  Wrench,
} from "@lucide/vue";

import type { StatusTone } from "@/components/StatusPill.vue";
import { positionBetween } from "@/components/kanban";

import type { Card, Health, PaletteColor, ProjectStatus, TaskStatus } from "./types";

/** `var(--c-chart-3)` for a palette key; the brand colour when there is none. */
export function colorVar(color: PaletteColor | string | null | undefined): string {
  return color && /^chart-[1-8]$/.test(color) ? `var(--c-${color})` : "var(--c-primary)";
}

/** A soft tint of a palette colour on the surface (card covers, label chips). */
export function tint(color: PaletteColor | string | null | undefined, percent = 16): string {
  return `color-mix(in srgb, ${colorVar(color)} ${percent}%, var(--c-surface))`;
}

export const HEALTH_TONE: Record<Health, StatusTone> = { on_track: "success", at_risk: "warning", off_track: "danger" };

export const STATUS_TONE: Record<ProjectStatus, StatusTone> = {
  planning: "info",
  active: "primary",
  on_hold: "warning",
  completed: "success",
  cancelled: "neutral",
};

export const TASK_TONE: Record<TaskStatus, StatusTone> = {
  todo: "neutral",
  in_progress: "info",
  review: "warning",
  returned: "danger",
  done: "success",
  cancelled: "neutral",
};

export function healthVar(health: Health | null | undefined): string {
  if (health === "off_track") return "var(--c-danger)";
  if (health === "at_risk") return "var(--c-warning)";
  if (health === "on_track") return "var(--c-success)";
  return "var(--c-subtle)";
}

/** Tone of a budget burn: over 100 % danger, from 85 % warning. */
export function burnTone(burn: number | null | undefined): "success" | "warning" | "danger" | "neutral" {
  if (burn === null || burn === undefined) return "neutral";
  if (burn > 100) return "danger";
  if (burn >= 85) return "warning";
  return "success";
}

export type DueState = "overdue" | "today" | "soon" | "later" | "done";

/** How a card's deadline reads: overdue, due today, within 2 days, later (or done). */
export function dueState(card: Pick<Card, "due_at" | "status">, now: number = Date.now()): DueState | null {
  if (!card.due_at) return null;
  if (card.status === "done") return "done";
  const due = new Date(card.due_at).getTime();
  if (due < now) return "overdue";
  const hours = (due - now) / 3_600_000;
  if (hours < 24 && new Date(card.due_at).toDateString() === new Date(now).toDateString()) return "today";
  if (hours < 48) return "soon";
  return "later";
}

export const DUE_CLASS: Record<DueState, string> = {
  overdue: "bg-danger-soft text-danger",
  today: "bg-warning-soft text-warning",
  soon: "bg-warning-soft text-warning",
  later: "bg-surface-2 text-muted",
  done: "bg-success-soft text-success",
};

/** "2:30" style hours for a minute count ("0:45", "12:00"). */
export function hhmm(minutes: number): string {
  const sign = minutes < 0 ? "-" : "";
  const total = Math.abs(Math.round(minutes));
  return `${sign}${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

/** Parses "1:30", "1.5", "90m", "2h", "45" (minutes when under 15, else... ) into minutes. */
export function parseDuration(text: string): number | null {
  const clean = text.trim().toLowerCase().replace(",", ".");
  if (!clean) return null;
  let match = /^(\d{1,2}):(\d{1,2})$/.exec(clean);
  if (match) return Number(match[1]) * 60 + Number(match[2]);
  match = /^(\d+(?:\.\d+)?)\s*(h|ч|soat|s)$/.exec(clean);
  if (match) return Math.round(Number(match[1]) * 60);
  match = /^(\d+)\s*(m|min|мин|daq|d)$/.exec(clean);
  if (match) return Number(match[1]);
  match = /^(\d+(?:\.\d+)?)$/.exec(clean);
  if (match) {
    const value = Number(match[1]);
    // "1.5" or "8" are hours; "45" or "90" are minutes.
    return value <= 12 ? Math.round(value * 60) : Math.round(value);
  }
  return null;
}

/** A position for a card dropped between two neighbours (float, like Trello). */
export function dropPosition(before: Pick<Card, "position"> | null, after: Pick<Card, "position"> | null): number {
  return positionBetween(before?.position ?? null, after?.position ?? null);
}

const ICONS: Record<string, Component> = {
  store: Store,
  globe: Globe,
  "clipboard-list": ClipboardList,
  backpack: Backpack,
  rocket: Rocket,
  megaphone: Megaphone,
  hammer: Hammer,
  truck: Truck,
  package: Package,
  building: Building2,
  sparkles: Sparkles,
  wrench: Wrench,
  "shopping-cart": ShoppingCart,
  "folder-kanban": FolderKanban,
};

export const ICON_NAMES = Object.keys(ICONS);

export function projectIcon(name: string | null | undefined): Component {
  return (name && ICONS[name]) || FolderKanban;
}

/** Board order: position, then id. */
export function cardSort(a: Card, b: Card): number {
  return a.position - b.position || a.id - b.id;
}

/** Whole days between two "YYYY-MM-DD" days (b − a). */
export function daysBetween(a: string, b: string): number {
  return Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86_400_000);
}

/**
 * Milestone labels sized to the room before the next diamond: shortened with "…" when the next
 * milestone is close, dropped when there is no room at all (the diamond stays; the Milestones tab
 * names them all), so crowded weeks stay readable.
 */
export function declutterMilestones<M extends { date: string; label: string }>(milestones: readonly M[], pxPerDay: number): M[] {
  const sorted = [...milestones].sort((a, b) => a.date.localeCompare(b.date));
  const first = sorted[0]?.date;
  const x = (milestone: M) => (first ? daysBetween(first, milestone.date) * pxPerDay : 0);
  const CHAR = 6.4;
  return sorted.map((milestone, index) => {
    const next = sorted[index + 1];
    if (!next) return milestone;
    const room = x(next) - x(milestone) - 30;
    if (room >= milestone.label.length * CHAR) return milestone;
    const chars = Math.floor(room / CHAR) - 1;
    return { ...milestone, label: chars >= 4 ? `${milestone.label.slice(0, chars).trimEnd()}…` : "" };
  });
}
