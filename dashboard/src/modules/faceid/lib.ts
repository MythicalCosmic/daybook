/** Small pure helpers of the Face ID pages (tested in __tests__/faceid.test.ts). */
import type { StatusTone } from "@/components/StatusPill.vue";

import type { DeviceStatus, Scan, ScanAction } from "./types";

/** The chip colour of what a scan did. */
export const ACTION_TONES: Record<ScanAction, StatusTone> = {
  checked_in: "success",
  checked_out: "info",
  seen: "primary",
  repeat: "neutral",
  not_linked: "warning",
  stranger: "danger",
  ignored: "neutral",
  module_off: "neutral",
};

/** The snapshot's ring, in the same colours (CSS variables of the design system). */
export const RING_COLORS: Record<ScanAction, string> = {
  checked_in: "var(--c-success)",
  checked_out: "var(--c-info)",
  seen: "var(--c-primary)",
  repeat: "var(--c-line-strong, var(--c-line))",
  not_linked: "var(--c-warning)",
  stranger: "var(--c-danger)",
  ignored: "var(--c-line-strong, var(--c-line))",
  module_off: "var(--c-line-strong, var(--c-line))",
};

export const STATUS_TONES: Record<DeviceStatus, StatusTone> = {
  online: "success",
  quiet: "warning",
  never: "neutral",
  disabled: "neutral",
};

/** The person a scan is about: the Daybook name, else the terminal's name, else its number. */
export function scanName(scan: Pick<Scan, "member" | "name_on_device" | "employee_no">): string {
  return scan.member?.name || scan.name_on_device || scan.employee_no || "";
}

/** "AV" for a name, for avatars without a snapshot (Cyrillic names too). */
export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  const letters = parts.length === 1 ? parts[0].slice(0, 2) : parts[0][0] + parts[parts.length - 1][0];
  return letters.toLocaleUpperCase();
}

/** The chip's words key and its values: "late 14 min" when the check-in was late. */
export function actionChip(scan: Pick<Scan, "action" | "record" | "flags">): { key: string; minutes?: number } {
  if (scan.flags.includes("simulated")) return { key: "faceid.action.test" };
  if (scan.action === "checked_in" && scan.record?.is_late) return { key: "faceid.action.late", minutes: scan.record.late_minutes };
  if (scan.action === "checked_out" && scan.record?.worked_minutes) return { key: "faceid.action.left", minutes: scan.record.worked_minutes };
  return { key: `faceid.action.${scan.action}` };
}

/** "HH:MM" of an ISO moment that carries its company's offset. */
export function clockOf(iso: string | null | undefined): string {
  return iso ? iso.slice(11, 16) : "";
}

/** The busiest hour of a terminal's day, for the sparkline's scale (never 0). */
export function peak(hourly: number[]): number {
  return Math.max(1, ...hourly);
}

/** The direction's words key. */
export const directionKey = (direction: string) => `faceid.direction.${direction}`;

/** The scans of a feed page that weren't there before (for the "new row" highlight). */
export function freshIds(previous: readonly number[], next: readonly { id: number }[]): number[] {
  const seen = new Set(previous);
  return next.filter((row) => !seen.has(row.id)).map((row) => row.id);
}
