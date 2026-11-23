/**
 * How Ko‘z draws on camera pictures. The colours sit on video, which looks the same in both
 * themes, so they are fixed here rather than theme tokens: warm peach for customers, mint for
 * pharmacists, amber then coral as a wait grows past the rule. Zones are soft tints with dashed
 * edges; a mask is a hatched black area.
 */
import type { AlertKind, CameraRole, PersonRole, ZoneKind } from "../types";

export const ROLE_COLOR: Record<PersonRole, string> = {
  customer: "#ffc58a",
  staff: "#7fd6aa",
};

export const WAIT_COLOR = { calm: "#ffffff", long: "#ffd36b", over: "#ff8466" } as const;

export const ZONE_COLOR: Record<ZoneKind, string> = {
  queue: "#ffb46e",
  staff: "#74d4a3",
  line: "#ffffff",
  floor: "#9cc8ff",
  mask: "#0b0b0b",
};

/** Lucide icon names are imported where used; this is the order the editor's tools appear in. */
export const ZONE_ORDER: readonly ZoneKind[] = ["queue", "staff", "line", "floor", "mask"];

/** The zones a role needs before Ko‘z counts on it (docs/KOZ.md §4, §5.8). */
export function missingZones(role: CameraRole, kinds: readonly ZoneKind[]): ZoneKind[] {
  if (role === "counter") return (["queue", "staff"] as const).filter((kind) => !kinds.includes(kind));
  if (role === "entrance") return kinds.includes("line") ? [] : ["line"];
  return [];
}

/** Severity of an open alert for ordering and colour: nobody at the counter first. */
export function alertWeight(kind: AlertKind): number {
  return kind === "unattended" ? 0 : kind === "queue" ? 1 : 2;
}

export const ALERT_TONE: Record<AlertKind, "warning" | "danger" | "neutral"> = {
  queue: "warning",
  unattended: "danger",
  agent_offline: "neutral",
};
