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

export type SetupAdmin = {
  username: string;
  password: string;
  first_name: string;
  last_name: string;
}

/** `POST edition/setup/` */
export type SetupInput = {
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
  /** null for a person whose role isn't one of the web roles (an employee who lost access). */
  role: UserRole | null;
  branch_ids: number[];
  is_active: boolean;
  last_login: string | null;
  telegram_linked: boolean;
  /** Also scans at the terminals. */
  is_employee?: boolean;
  /** The person signed in now. */
  is_self?: boolean;
}

export type UserInput = {
  username: string;
  password?: string;
  first_name: string;
  last_name: string;
  role_id: number;
  branch_ids: number[];
  /** Give an existing employee a sign-in instead of making a new person. */
  employee_id?: number | null;
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
  /** How they came in: added by hand, from an import, or by a terminal's unknown number. */
  source?: "manual" | "import" | "terminal" | string;
  today: EmployeeToday | null;
}

export type EmployeeInput = {
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
  /** Name, phone or face number. */
  search?: string;
  /** One branch (the server reads one). */
  branch?: number[];
  department?: number;
  position?: number;
  /** Empty: both. */
  status?: EmployeeStatus | "all";
  /** Telegram linked or not. */
  linked?: "1" | "0";
  /** Has face numbers or none. */
  face?: "1" | "0";
  page?: number;
  page_size?: number;
}

/** One row of an import's report: what it would do (or did), or why it can't. */
export interface ImportRow {
  /** The spreadsheet's row number (the header is row 1). */
  row: number;
  action: "create" | "update" | "skip";
  /** The person's name as read from the row. */
  name: string;
  /** The employee it matched (update) or made (create, after a real run). */
  employee_id: number | null;
  errors: string[];
}

/** `POST employees/import/` (with `?dry_run=1` only checks). */
export interface ImportResult {
  dry_run: boolean;
  /** The header row as read. */
  columns: string[];
  /** Header → field it was read as ("Ism" → "first_name"). */
  mapping: Record<string, string>;
  created: number;
  updated: number;
  skipped: number;
  /** At most the first few hundred rows. */
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

export type BranchInput = {
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

/** `GET/PATCH davomat/settings/`: the product's name on this install and the terminals' unknown numbers. */
export interface DavomatSettings {
  product_name: string;
  auto_create_employees: boolean;
}

/** `GET settings/` (the fields the organization panel edits). */
export interface Organization {
  id: number;
  name: string;
  logo: string | null;
  timezone: string;
  default_language: Language;
}
