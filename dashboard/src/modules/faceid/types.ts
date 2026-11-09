/**
 * Shapes of the Face ID endpoints (`faceid/…`, apps/faceid/owner_api.py), hand-written next to the
 * API functions; the generated schema checks them at integration.
 */
export type { Page } from "@/api/types";

export interface Ref {
  id: number;
  name: string;
}

export interface BranchRef extends Ref {
  code: string;
}

export interface PersonCard {
  id: number;
  name: string;
  photo_url: string | null;
  position: Ref | null;
  home_branch: Ref | null;
  status: string;
}

export type Direction = "in" | "out" | "toggle";
export type DeviceStatus = "online" | "quiet" | "never" | "disabled";
export type ScanAction = "checked_in" | "checked_out" | "seen" | "repeat" | "not_linked" | "stranger" | "ignored" | "module_off";
export type ScanKind = "person" | "stranger" | "other";
export type ScanMethod = "face" | "fingerprint" | "card" | "other" | "";
export type TelegramMode = "off" | "arrivals" | "every_scan";

/** The stored history a terminal uploads when first pointed at Daybook: skipped, only counted. */
export interface DeviceHistory {
  skipped: number;
  /** The newest skipped scan's time. */
  until: string | null;
  /** Old scans are still coming; live scans start after them. */
  active: boolean;
  /** The terminal's clock is so far behind that its live scans look old too (and are skipped). */
  clock_hides: boolean;
}

export interface Device {
  id: number;
  name: string;
  branch: BranchRef;
  direction: Direction;
  enabled: boolean;
  vendor: string;
  model: string;
  ip: string;
  mac: string;
  status: DeviceStatus;
  last_seen_at: string | null;
  last_event_at: string | null;
  heartbeats: boolean;
  clock_offset_s: number | null;
  clock_off: boolean;
  scans_today: number;
  /** Scans per hour today, 0–23. */
  hourly: number[];
  last_scan: { at: string; name: string; action: ScanAction } | null;
  history: DeviceHistory;
  created_at: string;
}

export interface DeviceInput {
  name: string;
  branch_id: number;
  direction: Direction;
}

export interface Setup {
  host: string;
  addressing: "hostname" | "ipaddress";
  path: string;
  recommended: "https" | "http";
  heartbeat_minutes: number;
  http: { port: number; url: string };
  https: { port: number; url: string };
  last_event_at: string | null;
  last_seen_at: string | null;
  last_test_at: string | null;
  history: DeviceHistory;
}

export interface RecordBrief {
  id: number;
  status: string;
  check_in_at: string | null;
  check_out_at: string | null;
  is_late: boolean;
  late_minutes: number;
  worked_minutes: number;
}

export interface Scan {
  id: number;
  event_at: string;
  received_at: string;
  device: Ref;
  branch: BranchRef;
  kind: ScanKind;
  action: ScanAction;
  method: ScanMethod;
  verify_mode: string;
  employee_no: string;
  name_on_device: string;
  member: PersonCard | null;
  record: RecordBrief | null;
  flags: string[];
  photo_url: string | null;
}

export interface ScanParams {
  device?: number;
  action?: ScanAction[];
  member?: number;
  number?: string;
  date?: string;
  branch?: number[];
  tests?: "1";
  page_size?: number;
}

export interface Suggestion {
  member: PersonCard;
  score: number;
  has_number: boolean;
}

export interface KnownPerson {
  employee_no: string;
  name_on_device: string;
  first_at: string;
  last_at: string;
  scans: number;
  device: Ref;
  photo_url: string | null;
  member: PersonCard | null;
  link: { id: number; auto: boolean; ignored: boolean } | null;
  suggestions: Suggestion[];
}

export interface Link {
  id: number;
  employee_no: string;
  member: PersonCard | null;
  auto: boolean;
  ignored: boolean;
  created_at: string;
}

export interface Status {
  total: number;
  online: number;
  quiet: number;
  never: number;
  unlinked: number | null;
  devices: Array<{ id: number; name: string; branch: BranchRef; status: DeviceStatus; last_event_at: string | null; scans_today: number }>;
}

export interface FaceIdSettings {
  attendance: boolean;
  telegram: TelegramMode;
  group_posts: boolean;
  group_photos: boolean;
  notify_employee: boolean;
  alert_strangers: boolean;
  repeat_minutes: number;
  photo_days: number;
}
