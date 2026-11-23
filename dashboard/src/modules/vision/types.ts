/**
 * Ko‘z response shapes, written from docs/KOZ.md §4 and §6 (the contract the backend serializers
 * follow). Times are ISO instants in UTC; coordinates are normalized to 0..1 of the frame (x to the
 * right, y down); money is a decimal string.
 */
import type { Money } from "@/api/types";

export interface Ref {
  id: number;
  name: string;
}

export type CameraRole = "counter" | "entrance" | "floor" | "storeroom" | "other";
export const CAMERA_ROLES: readonly CameraRole[] = ["counter", "entrance", "floor", "storeroom", "other"];

export type CameraSource = "nvr" | "rtsp" | "webcam" | "file" | "sim";

// ─── Zones (§4) ─────────────────────────────────────────────────────────────

export type ZoneKind = "queue" | "staff" | "line" | "floor" | "mask";
export const ZONE_KINDS: readonly ZoneKind[] = ["queue", "staff", "line", "floor", "mask"];

/** A point as [x, y], each 0..1. */
export type Point = [number, number];

export interface Zone {
  id: string;
  kind: ZoneKind;
  points: Point[];
  /** Lines only: the side of the directed line A→B that is inside the pharmacy. */
  in?: "left" | "right";
}

// ─── Cameras (§6.4) ─────────────────────────────────────────────────────────

export interface Camera {
  id: number;
  key: string;
  name: string;
  role: CameraRole;
  enabled: boolean;
  branch: Ref;
  agent_id: number | null;
  source: CameraSource;
  channel: number | null;
  w: number | null;
  h: number | null;
  online: boolean;
  last_seen_at: string | null;
  zones: Zone[];
  register: Ref | null;
  snapshot_url: string | null;
  snapshot_at: string | null;
}

export interface CameraPatch {
  name?: string;
  role?: CameraRole;
  enabled?: boolean;
  zones?: Zone[];
  register_id?: number | null;
}

// ─── Live (§6.2, §6.3) ──────────────────────────────────────────────────────

export interface LiveCamera {
  id: number;
  name: string;
  role: CameraRole;
  branch_id: number;
  online: boolean;
  /** No live report for 30 s. */
  stale: boolean;
  people: number | null;
  queue: number | null;
  staff: number | null;
  wait_s: number | null;
  fps: number | null;
}

export interface Live {
  at: string;
  today: { visitors: number | null; receipts: number | null };
  cameras: LiveCamera[];
  open_alerts: Alert[];
}

export type PersonRole = "customer" | "staff";

export interface FramePerson {
  track: number;
  /** [x, y, w, h], normalized. */
  box: [number, number, number, number];
  role: PersonRole;
  zone: string | null;
  /** Only inside a queue zone. */
  wait_s?: number | null;
}

export interface Frame {
  at: string;
  w: number;
  h: number;
  people: FramePerson[];
  image_b64: string;
}

// ─── Alerts (§6.5) ──────────────────────────────────────────────────────────

export type AlertKind = "queue" | "unattended" | "agent_offline";
export const ALERT_KINDS: readonly AlertKind[] = ["queue", "unattended", "agent_offline"];
export type AlertState = "open" | "resolved";

export interface ClipRef {
  id: number;
  state: ClipState;
}

export interface Alert {
  id: number;
  kind: AlertKind;
  state: AlertState;
  branch: Ref;
  /** None for a box that went offline. */
  camera: Ref | null;
  started_at: string;
  resolved_at: string | null;
  duration_s: number | null;
  peak_queue: number | null;
  peak_wait_s: number | null;
  acknowledged_by: Ref | null;
  acknowledged_at: string | null;
  photo_url: string | null;
  clip: ClipRef | null;
}

export interface AlertParams {
  branch?: number;
  state?: AlertState;
  kind?: AlertKind;
  from?: string;
  to?: string;
  page?: number;
  page_size?: number;
}

// ─── Clips (§6.6) ───────────────────────────────────────────────────────────

export type ClipState = "pending" | "fetching" | "ready" | "failed";
export type ClipFailure = "not_recorded" | "camera_offline" | "nvr_error" | "too_old" | "agent_timeout";
export const CLIP_FAILURES: readonly ClipFailure[] = ["not_recorded", "camera_offline", "nvr_error", "too_old", "agent_timeout"];

export interface Clip {
  id: number;
  state: ClipState;
  reason: "sale" | "alert" | "manual";
  camera: Ref | null;
  start: string;
  end: string;
  sale_id: number | null;
  alert_id: number | null;
  video_url: string | null;
  poster_url: string | null;
  duration_s: number | null;
  failure: ClipFailure | string | null;
  failure_text: string | null;
  created_at: string;
}

/** What a clip is asked for: a sale, an alert, or a camera at a moment. */
export type ClipRequest =
  | { sale_id: number }
  | { alert_id: number }
  | { camera_id: number; at: string; before_s?: number; after_s?: number };

// ─── Overview (§6.1) ────────────────────────────────────────────────────────

export interface AgentBrief {
  id: number;
  name: string;
  branch_id: number;
  online: boolean;
  last_seen_at: string | null;
  version: string | null;
}

export interface Totals {
  visitors: number | null;
  receipts: number | null;
  /** 0..1, or null (no visitors, or more receipts than visitors). */
  conversion: number | null;
  conversion_note: "entrance_undercount" | string | null;
  left: number | null;
  wait_avg_s: number | null;
  wait_max_s: number | null;
  alerts: number | null;
  unattended_minutes: number | null;
  compare: {
    visitors: number | null;
    receipts: number | null;
    conversion: number | null;
    label: "same_weekday_last_week" | string;
  } | null;
}

export interface HourRow {
  hour: number;
  visitors: number | null;
  receipts: number | null;
  queue_max: number | null;
  wait_max_s: number | null;
  staff_avg: number | null;
  staff_checked_in: number | null;
  unattended_minutes: number | null;
}

export type InsightKind = "lost_peak" | "long_wait" | "unattended" | "staff_gap" | "good_day";
export type Severity = "info" | "warn" | "bad" | "good";

export interface Insight {
  kind: InsightKind | string;
  severity: Severity;
  hour: number | null;
  text: string;
}

export interface Overview {
  day: string;
  branch: Ref | null;
  setup: { agents: number; cameras: number; entrance: boolean; counter: boolean };
  agents: AgentBrief[];
  totals: Totals;
  hours: HourRow[];
  insights: Insight[];
  open_alerts: Alert[];
}

// ─── Settings (§6.7) ────────────────────────────────────────────────────────

export interface VisionSettings {
  queue_people: number;
  queue_wait_s: number;
  unattended_s: number;
  clear_after_s: number;
  cooldown_s: number;
  analysis_fps: number;
  live_fps: number;
  privacy_blur: boolean;
  alert_photo: boolean;
  record_counter: boolean;
  record_hours: number;
  notify_on_shift: boolean;
  notify_managers: boolean;
  stats_keep_days: number;
  photos_keep_days: number;
  clips_keep_days: number;
}

// ─── Boxes (§6.8) ───────────────────────────────────────────────────────────

export interface Agent {
  id: number;
  name: string;
  branch: Ref;
  online: boolean;
  last_seen_at: string | null;
  version: string | null;
  host: { hostname: string; os: string } | null;
  paired: boolean;
  cameras: number;
  created_at: string;
}

export interface Pairing {
  code: string;
  expires_at: string;
  command: string;
}

// ─── Review (§6.9) ──────────────────────────────────────────────────────────

export interface ReviewItem {
  kind: "void" | "payout";
  at: string;
  amount: Money;
  sale_id: number | null;
  cash_movement_id: number | null;
  cashier: Ref | null;
  camera: Ref | null;
  queue_max: number;
  clip: ClipRef | null;
}
