/**
 * Shapes of Davomat's endpoints (docs/DAVOMAT.md §1, `apps/davomat/owner_api.py`), hand-written
 * next to the API functions; the generated schema checks them at integration. Instants are ISO
 * strings (UTC), days are company-local "YYYY-MM-DD".
 */
import type { Language } from "@/api/types";

export type { Page } from "@/api/types";

export interface Ref {
  id: number;
  name: string;
}

// First run (§1.1) -----------------------------------------------------------------------------

export interface SetupAdmin {
  username: string;
  password: string;
  first_name: string;
  last_name: string;
}

/** `POST edition/setup/` */
export interface SetupInput {
  organization: string;
  timezone: string;
  language: Language;
  admin: SetupAdmin;
}

// Users (§1.3) ---------------------------------------------------------------------------------

export type RoleKind = "owner" | "admin" | "manager" | "viewer";

export interface UserRole {
  id: number;
  name: string;
  kind: RoleKind;
}

/** One person who signs in to the web app (`companies/{c}/users/`); `id` is the membership id. */
export interface User {
  id: number;
  username: string;
  first_name: string;
  last_name: string;
  role: UserRole;
  branch_ids: number[];
  is_active: boolean;
  last_login: string | null;
  telegram_linked: boolean;
}

export interface UserInput {
  username: string;
  password?: string;
  first_name: string;
  last_name: string;
  role_id: number;
  branch_ids: number[];
}

export type UserPatch = Partial<Omit<UserInput, "password">> & { is_active?: boolean };

// Employees (§1.4) -----------------------------------------------------------------------------

export type EmployeeStatus = "active" | "left";
/** Today at the door: in the building, gone home, not in yet, a day off, on leave. */
export type TodayState = "in" | "out" | "not_in" | "off" | "leave";

export interface EmployeeToday {
  state: TodayState;
  /** When that state began (the check-in for "in", the check-out for "out"). */
  since: string | null;
}

export interface Employee {
  id: number;
  first_name: string;
  last_name: string;
  full_name: string;
  photo_url: string | null;
  phone: string;
  position: Ref | null;
  department: Ref | null;
  branch_ids: number[];
  /** The numbers the terminals know this person by ("00000002"). */
  face_numbers: string[];
  status: EmployeeStatus;
  hire_date: string | null;
  left_on: string | null;
  schedule: Ref | null;
  telegram_linked: boolean;
  /** Also signs in to the web app. */
  is_user: boolean;
  today: EmployeeToday | null;
}

export interface EmployeeInput {
  first_name: string;
  last_name: string;
  phone: string;
  position_id: number | null;
  department_id: number | null;
  branch_ids: number[];
  face_numbers: string[];
  schedule_id: number | null;
  hire_date: string | null;
}

export interface EmployeeParams {
  search?: string;
  branch?: number[];
  department?: number;
  position?: number;
  status?: EmployeeStatus | "all";
  linked?: "1" | "0";
  page?: number;
  page_size?: number;
}

/** One row of an import's preview: what it would create or change, or why it can't. */
export interface ImportRow {
  /** 1-based, as in the spreadsheet (after its header row). */
  row: number;
  action: "create" | "update" | "skip";
  first_name: string;
  last_name: string;
  phone: string;
  position: string;
  department: string;
  branch: string;
  face_number: string;
  errors: string[];
}

/** `POST employees/import/` (with `?dry_run=1` only checks). */
export interface ImportResult {
  dry_run: boolean;
  total: number;
  created: number;
  updated: number;
  skipped: number;
  errors: number;
  rows: ImportRow[];
}

// Telegram (§1.5) ------------------------------------------------------------------------------

export type BotStatus = "ok" | "invalid" | "not_set";

/** `GET/PUT companies/{c}/telegram/` (the token is write-only). */
export interface TelegramSettings {
  configured: boolean;
  bot_username: string | null;
  bot_name: string | null;
  status: BotStatus;
  checked_at: string | null;
}

/** A one-time link that ties a Telegram account to a person (24 hours, one use). */
export interface TelegramLink {
  url: string;
  code: string;
  expires_at: string;
}

// Shared lists the Team pages read ------------------------------------------------------------

/** `GET branches/` (the fields Davomat shows). */
export interface Branch {
  id: number;
  name: string;
  code: string;
  address: string;
  phone: string;
  opens_at: string | null;
  closes_at: string | null;
  open_24h: boolean;
  is_active: boolean;
  order: number;
  /** Approved people working there. */
  people: number;
}

export interface BranchInput {
  name: string;
  code?: string;
  address?: string;
  phone?: string;
}

/** `GET departments/` */
export interface Department {
  id: number;
  name: string;
  parent_id: number | null;
  head: { id: number; name: string } | null;
  member_count: number;
  total_count: number;
  path: string[];
  can_edit: boolean;
}

/** `GET positions/` */
export interface Position {
  id: number;
  name: string;
  order: number;
  is_active: boolean;
  members_count: number;
}

/** `GET attendance/schedules/` (the fields the employee form needs). */
export interface ScheduleOption {
  id: number;
  name: string;
  kind: string;
  is_active: boolean;
}

/** `GET settings/` (the fields the organization panel edits). */
export interface Organization {
  id: number;
  name: string;
  logo: string | null;
  timezone: string;
  default_language: Language;
}
