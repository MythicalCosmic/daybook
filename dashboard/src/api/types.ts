/**
 * Shared API shapes (plan §4). Module types live next to each module's api.ts; only shapes that the
 * shell or several modules read belong here. Money is always a decimal string ("1250000.00") and
 * dates are ISO strings: company-local "YYYY-MM-DD" for days, full ISO 8601 for instants.
 *
 * The console shapes below are written from the W0 serializers (`apps.console.owner_api`,
 * `apps.inbox.serializers`, `apps.exports.owner_api`, `apps.audit.owner_api`, `apps.signin`).
 */
import type { CompanyFeature } from "@/core/features";
import type { Perm } from "@/core/perms";

export type Language = "uz" | "ru" | "en";
export const LANGUAGES: readonly Language[] = ["uz", "ru", "en"];

export type Currency = "UZS" | "USD";

/** A decimal amount as the API sends it. Never parse it with parseFloat for arithmetic. */
export type Money = string;

export interface MoneyValue {
  amount: Money;
  currency: Currency;
}

/** DRF page-number pagination (`page`, `page_size` ≤ 200, 50 by default). */
export interface Page<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

/** A company-local day range, both ends inclusive. */
export interface Range {
  from: string;
  to: string;
}

/** The one analytics shape every KPI and chart endpoint returns (plan §4). */
export interface Summary<K extends string = string> {
  range: Range;
  compare: Range | null;
  currency: Currency;
  totals: Record<K, Money | number>;
  previous: Record<K, Money | number> | null;
  series: Array<{ date: string } & Partial<Record<K, Money | number>>>;
  breakdown: Array<{ key: string; label: string } & Partial<Record<K, Money | number>>>;
}

/** A person as most endpoints name them: their membership id and display name (a photo when the endpoint has one). */
export interface PersonRef {
  id: number;
  name: string;
  photo_url?: string | null;
}

export interface BranchRef {
  id: number;
  name: string;
  code: string;
}

export interface RoleRef {
  id: number;
  name: string;
}

/**
 * One company in `me.companies` (plan §4.2): every company where the caller has `dashboard.access`.
 * `alerts` is W0-D's request to W0-L (the open red alerts behind the switcher's status dot, §13.2);
 * it stays optional until `me/` sends it.
 */
export interface Company {
  id: number;
  name: string;
  logo: string | null;
  timezone: string;
  base_currency: Currency;
  features: CompanyFeature[];
  /** null only for a membership without a role (never an owner). */
  role: RoleRef | null;
  /** Owners hold every permission. */
  is_owner: boolean;
  permissions: Perm[];
  /** Branch ids the caller is limited to; null means every branch (owners and `branches.all`); [] means none (§2.6). */
  branch_scope: number[] | null;
  /** Branches the caller may see, in display order. */
  branches: BranchRef[];
  home_branch: { id: number; name: string } | null;
  /** "Needs you" items waiting for the caller here (company switcher count). */
  pending: number;
  /** "Get started" is finished or dismissed. */
  setup_completed: boolean;
  /** The caller's own membership in this company (the id other endpoints use for people). */
  membership_id: number;
  alerts?: number;
}

export interface MeUser {
  id: number;
  telegram_id: number | null;
  first_name: string;
  last_name: string;
  full_name: string;
  /** Telegram username without "@"; may be empty. */
  username: string;
  photo_url: string | null;
}

/** `GET /owner/me/` (no platform-admin flag: platform admins work in the Django admin, plan appendix #2). */
export interface Me {
  user: MeUser;
  language: Language;
  companies: Company[];
}

/** `GET /owner/permissions/`: the registry for the roles matrix. */
export interface PermissionInfo {
  code: Perm;
  label: string;
  /** The code's prefix ("sales"). */
  group: string;
}

/** `GET O pulse/`: counters filtered by permission, and version stamps that change on writes. */
export interface Pulse {
  counters: Record<string, number>;
  versions: Record<string, string>;
}

/**
 * One palette result from `GET O search/`. `type` is the provider's app-prefixed key
 * ("members.people", "tasks"); `url` is a dashboard path, absolute ("/c/12/people/17") or relative
 * to the company ("people/17").
 */
export interface SearchHit {
  type: string;
  id: number | string;
  title: string;
  subtitle: string;
  url: string;
}

export interface SearchResponse {
  results: SearchHit[];
}

export type ActionStyle = "primary" | "danger" | "default";

/**
 * A button on a "Needs you" item (plan §2.5): the shell sends `method` to `endpoint`, which is
 * relative to `/api/v1/owner/companies/{cid}/` (e.g. "time-off/42/approve/"), with `body` plus
 * `reason` when `needs_reason`.
 */
export interface QueueAction {
  key: string;
  label: string;
  style: ActionStyle;
  method: "POST" | "PATCH" | "PUT" | "DELETE";
  endpoint: string;
  body: Record<string, unknown>;
  needs_reason: boolean;
}

/** One "Needs you" item. `kind` is the registered queue kind ("timeoff.requests"); `url` a dashboard path. */
export interface QueueItem {
  kind: string;
  id: number | string;
  title: string;
  subtitle: string;
  created_at: string | null;
  url: string;
  actions: QueueAction[];
}

/** `GET O queue/?kind=&limit=`: oldest first, at most `limit` (50) per kind. */
export interface QueueItemsResponse {
  items: QueueItem[];
}

export interface QueueKind {
  kind: string;
  label: string;
  count: number;
}

/** `GET O queue/counts/` */
export interface QueueCounts {
  total: number;
  kinds: QueueKind[];
}

/** The queue as the console shows it: counts and labels per kind with the items (both calls at once). */
export interface QueueView extends QueueCounts {
  items: QueueItem[];
}

export type Severity = "info" | "warning" | "critical";

export interface NotificationAction {
  key: string;
  label: string;
  style: ActionStyle;
  needs_reason: boolean;
}

/** One row of `GET O inbox/` (`apps.inbox.serializers.NotificationSerializer`). */
export interface Notification {
  id: number;
  /** The registered kind ("sales.cash_difference"); a module may render it (`DashboardModule.inbox`). */
  kind: string;
  severity: Severity;
  title: string;
  body: string;
  /** Dashboard route ("/c/12/sales/shifts/1042"); may be empty. */
  url: string;
  /** Mini app deep link; unused by the console. */
  app_screen: string;
  target_type: string;
  target_id: number | null;
  actor: PersonRef | null;
  /** Buttons; empty once someone acted. */
  actions: NotificationAction[];
  data: Record<string, unknown>;
  created_at: string;
  read_at: string | null;
  acted_at: string | null;
  /** Who acted, as a display name. */
  acted_by: string | null;
}

/** `GET O inbox/unread-count/` */
export interface UnreadCount {
  count: number;
  critical: number;
}

/** `POST O inbox/{id}/actions/{key}/` */
export interface NotificationActionResult {
  message: string;
  notification: Notification;
}

/** `GET O stream/?since=&limit=`: the activity stream, newest first. */
export interface StreamItem {
  at: string;
  kind: string;
  actor: PersonRef | null;
  title: string;
  url: string;
  photo_url: string | null;
}

export type BranchStatus = "open" | "not_opened" | "closed" | "day_off";

/** `GET O branches/today/`: one branch card; a facts key is absent when its module is off or hidden (§2.5). */
export interface BranchToday {
  id: number;
  name: string;
  code: string;
  /** "HH:MM", company time. */
  opens_at: string | null;
  closes_at: string | null;
  status: BranchStatus;
  sales?: { opened_at: string | null; opened_by: PersonRef | null; open_tills: number; net: Money; cash_in_branch: Money };
  attendance?: { rostered: number; checked_in: number; first_check_in: string | null };
  tasks?: { done: number; total: number; late: number };
  finance?: { cash: Money };
}

export type ExportFormat = "xlsx" | "csv" | "zip";
export type ExportStatus = "pending" | "running" | "ready" | "failed";

/** One export (`GET O exports/`, `exports/{id}/`), kept 7 days. */
export interface ExportJob {
  id: number;
  kind: string;
  /** The exporter's name ("Tasks"), in the caller's language. */
  label: string;
  format: ExportFormat;
  params: Record<string, unknown>;
  status: ExportStatus;
  rows: number | null;
  error: string;
  deliver_telegram: boolean;
  sensitive: boolean;
  created_at: string;
  finished_at: string | null;
  expires_at: string;
  file_name: string | null;
  /** Signed for 10 minutes, checked again when used; null until ready. */
  file_url: string | null;
}

export type ExportColumnKind = "text" | "number" | "money" | "date" | "datetime" | "bool";

/** `GET O exports/kinds/`: what the caller may export here. */
export interface Exporter {
  kind: string;
  label: string;
  sensitive: boolean;
  formats: ExportFormat[];
  columns: Array<{ key: string; label: string; kind: ExportColumnKind }>;
}

/** `POST /owner/auth/refresh/`, `dev-login/`, `telegram/` */
export interface AccessResponse {
  access: string;
}
