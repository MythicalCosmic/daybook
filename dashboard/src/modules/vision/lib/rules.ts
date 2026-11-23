/**
 * The contract's defaults (docs/KOZ.md §6.7) and their limits: the settings page shows each
 * default beside its value, and the live view uses them until the company's settings arrive.
 */
import type { CameraRole, VisionSettings } from "../types";

export const DEFAULT_RULES: VisionSettings = {
  queue_people: 3,
  queue_wait_s: 120,
  unattended_s: 90,
  clear_after_s: 15,
  cooldown_s: 120,
  analysis_fps: 2,
  live_fps: 2,
  privacy_blur: false,
  alert_photo: true,
  record_counter: true,
  record_hours: 24,
  notify_on_shift: true,
  notify_managers: true,
  stats_keep_days: 400,
  photos_keep_days: 30,
  clips_keep_days: 30,
};

export type NumericSetting = {
  [K in keyof VisionSettings]: VisionSettings[K] extends number ? K : never;
}[keyof VisionSettings];

export const LIMITS: Record<NumericSetting, [min: number, max: number]> = {
  queue_people: [1, 20],
  queue_wait_s: [15, 1800],
  unattended_s: [15, 1800],
  clear_after_s: [5, 120],
  cooldown_s: [0, 3600],
  analysis_fps: [1, 5],
  live_fps: [1, 4],
  record_hours: [1, 168],
  stats_keep_days: [30, 800],
  photos_keep_days: [1, 365],
  clips_keep_days: [1, 365],
};

/** The order cameras are listed in: the counter first, as it matters most. */
export const ROLE_ORDER: readonly CameraRole[] = ["counter", "entrance", "floor", "storeroom", "other"];

/** A number inside its limits (a typed 0 or 9999 is pulled back, never sent). */
export function clampSetting(key: NumericSetting, value: number): number {
  const [min, max] = LIMITS[key];
  if (!Number.isFinite(value)) return DEFAULT_RULES[key];
  return Math.min(max, Math.max(min, Math.round(value)));
}

/** The settings that differ from the saved ones, ready for PATCH. */
export function changedSettings(saved: VisionSettings, draft: VisionSettings): Partial<VisionSettings> {
  const out: Partial<VisionSettings> = {};
  for (const key of Object.keys(draft) as Array<keyof VisionSettings>) {
    if (draft[key] !== saved[key]) (out as Record<string, unknown>)[key] = draft[key];
  }
  return out;
}
