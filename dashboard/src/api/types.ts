/**
 * Shared API shapes (plan §4). Module types live next to each module's api.ts; only shapes that the
 * shell or several modules read belong here. Money is always a decimal string ("1250000.00") and
 * dates are ISO strings: company-local "YYYY-MM-DD" for days, full ISO 8601 for instants.
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

/** DRF page-number pagination. */
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

export interface PersonRef {
  id: number;
  name: string;
  photo_url: string | null;
}

export interface BranchRef {
  id: number;
  name: string;
  code: string;
}

export interface RoleRef {
  id: number;
  name: string;
  is_owner: boolean;
}

/** One company in `me.companies`: every company where the caller has `dashboard.access`. */
export interface Company {
  id: number;
  name: string;
  logo: string | null;
  timezone: string;
  base_currency: Currency;
  language: Language;
  features: CompanyFeature[];
  /** The caller's own membership in this company. */
  membership_id: number;
  role: RoleRef;
  permissions: Perm[];
  /** Branch ids the caller is limited to; null means every branch (owners and `branches.all`). */
  branch_scope: number[] | null;
  branches: BranchRef[];
  /** "Needs you" items waiting for the caller here (company switcher count). */
  pending: number;
  /** Open red alerts (company switcher status dot, §13.1). */
  alerts: number;
}

export interface MeUser {
  id: number;
  telegram_id: number;
  first_name: string;
  last_name: string;
  full_name: string;
  username: string;
  photo_url: string | null;
}

/** `GET /owner/me/` */
export interface Me {
  user: MeUser;
  language: Language;
  is_platform_admin: boolean;
  companies: Company[];
}

/** `GET O pulse/`: counters filtered by permission, and version stamps that change on writes. */
export interface Pulse {
  counters: Record<string, number>;
  versions: Record<string, string>;
}

/** One palette result from `GET O search/`. `url` is a dashboard path relative to the company. */
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

/** A button on a "Needs you" item; the shell calls `endpoint` with `method` (plan §2.4). */
export interface QueueAction {
  key: string;
  label: string;
  style: ActionStyle;
  method: "POST" | "PATCH" | "DELETE";
  endpoint: string;
  needs_reason: boolean;
}

export interface QueueItem {
  kind: string;
  id: number | string;
  title: string;
  subtitle: string;
  created_at: string;
  url: string;
  actions: QueueAction[];
  photo_url?: string | null;
  actor?: PersonRef | null;
}

export interface QueueKind {
  kind: string;
  label: string;
  count: number;
}

/** `GET O queue/` */
export interface QueueResponse {
  total: number;
  kinds: QueueKind[];
  results: QueueItem[];
}

export type Severity = "info" | "warning" | "critical";

export interface NotificationAction {
  key: string;
  label: string;
  style: ActionStyle;
  needs_reason?: boolean;
}

/** One row of `GET O inbox/`. */
export interface Notification {
  id: number;
  kind: string;
  severity: Severity;
  title: string;
  body: string;
  url: string;
  created_at: string;
  read_at: string | null;
  acted_at: string | null;
  actor: PersonRef | null;
  actions: NotificationAction[];
  data: Record<string, unknown>;
  photo_url?: string | null;
}

export interface UnreadCount {
  count: number;
  critical: number;
}

/** `POST /owner/auth/refresh/`, `dev-login/`, `telegram/` */
export interface AccessResponse {
  access: string;
}
