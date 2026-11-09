/** Small pure helpers of the Team pages (tested in __tests__/team.lib.test.ts). */
import type { StatusTone } from "@/components/StatusPill.vue";

import type { EmployeeStatus, TodayState } from "../../types";
import type { DeviceStatus, ScanAction } from "../overview/overviewApi";
import type { CellCode } from "./teamApi";

/** The chip colour of where someone is today. */
export const TODAY_TONES: Record<TodayState, StatusTone> = {
  in: "success",
  out: "info",
  not_in: "warning",
  off: "neutral",
  leave: "primary",
};

export const STATUS_TONES: Record<EmployeeStatus, StatusTone> = {
  active: "success",
  left: "neutral",
};

export const DEVICE_DOTS: Record<DeviceStatus, string> = {
  online: "var(--c-success)",
  quiet: "var(--c-warning)",
  never: "var(--c-subtle)",
  disabled: "var(--c-subtle)",
};

/** A scan's chip colour, its snapshot ring the same (FaceThumb takes the same tones). */
export const SCAN_TONES: Record<ScanAction, StatusTone> = {
  checked_in: "success",
  checked_out: "info",
  seen: "primary",
  repeat: "neutral",
  not_linked: "warning",
  stranger: "danger",
  ignored: "neutral",
  module_off: "neutral",
};

/** The calendar's day colours (tokens only), the same codes the attendance timesheet uses. */
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
  planned: "text-subtle ring-1 ring-inset ring-line-strong",
  off: "text-subtle",
};

/** Codes whose cell shows the hours worked. */
export const CELL_WITH_HOURS: ReadonlySet<CellCode> = new Set(["present", "late", "auto", "unscheduled"]);

/** A terminal's person number: what the device shows as Employee No. (up to 32 letters, digits, - and _). */
export const FACE_NUMBER = /^[A-Za-z0-9_-]{1,32}$/;

/** The numbers typed or pasted at once ("2, 15 0031"), trimmed, without repeats. */
export function splitFaceNumbers(text: string): string[] {
  return [...new Set(text.split(/[\s,;]+/).map((part) => part.trim()).filter(Boolean))];
}

/** Names of the locations an employee works at, in the company's order. */
export function branchNames(ids: readonly number[], branches: ReadonlyArray<{ id: number; name: string }>): string[] {
  const wanted = new Set(ids);
  return branches.filter((branch) => wanted.has(branch.id)).map((branch) => branch.name);
}

/** "MK" for a name (Cyrillic too), for photos that aren't there. */
export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  const letters = parts.length === 1 ? parts[0]!.slice(0, 2) : parts[0]![0]! + parts[parts.length - 1]![0]!;
  return letters.toLocaleUpperCase();
}

/** "2026-11" of a day. */
export const monthOf = (day: string) => day.slice(0, 7);

export function shiftMonth(month: string, delta: number): string {
  const [y, m] = month.split("-").map(Number) as [number, number];
  const date = new Date(Date.UTC(y, m - 1 + delta, 1));
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}`;
}

/** 0 = Monday … 6 = Sunday. */
export function weekdayIndex(day: string): number {
  const [y, m, d] = day.split("-").map(Number) as [number, number, number];
  return (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7;
}

/** Minutes as hours with one decimal at most, without units ("7.5"). */
export function hoursOf(minutes: number): number {
  return Math.round((minutes / 60) * 10) / 10;
}

/**
 * The template the import accepts: one header row with the columns the server reads
 * (`apps/davomat` import: first and last name, phone, position, department, branch, face number,
 * hire date) and one example row, as CSV (Excel opens it; UTF-8 with a BOM so Cyrillic stays readable).
 */
export const IMPORT_COLUMNS = ["first_name", "last_name", "phone", "position", "department", "branch", "face_number", "hire_date"] as const;
export type ImportColumn = (typeof IMPORT_COLUMNS)[number];

export function isImportColumn(value: string): value is ImportColumn {
  return (IMPORT_COLUMNS as readonly string[]).includes(value);
}

export function importTemplate(example: readonly string[]): string {
  const quote = (value: string) => (/[",\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value);
  return `﻿${IMPORT_COLUMNS.join(",")}\n${example.map(quote).join(",")}\n`;
}

// ─── The photo cropper's arithmetic (frame pixels; the image's top-left corner at x, y) ────────

/** The scale at which an image just covers a square `frame` (its shorter side fills it). */
export function coverScale(width: number, height: number, frame: number): number {
  return frame / Math.min(width, height);
}

/** Keeps the image covering the frame: its edges never come inside it. */
export function clampOffset(width: number, height: number, frame: number, scale: number, x: number, y: number): { x: number; y: number } {
  const w = width * scale;
  const h = height * scale;
  return { x: Math.min(0, Math.max(frame - w, x)), y: Math.min(0, Math.max(frame - h, y)) };
}

/** The image centred in the frame at `scale`. */
export function centred(width: number, height: number, frame: number, scale: number): { x: number; y: number } {
  return { x: (frame - width * scale) / 2, y: (frame - height * scale) / 2 };
}

/**
 * A new zoom around the frame's centre: the point under the centre stays there, then the image is
 * kept covering the frame.
 */
export function zoomAround(width: number, height: number, frame: number, from: { scale: number; x: number; y: number }, scale: number): { x: number; y: number } {
  const cx = (frame / 2 - from.x) / from.scale;
  const cy = (frame / 2 - from.y) / from.scale;
  return clampOffset(width, height, frame, scale, frame / 2 - cx * scale, frame / 2 - cy * scale);
}

/** The square of the source image the frame shows (source pixels), for drawing the result. */
export function sourceSquare(frame: number, scale: number, x: number, y: number): { sx: number; sy: number; size: number } {
  return { sx: -x / scale, sy: -y / scale, size: frame / scale };
}
