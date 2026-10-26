/**
 * Shapes of the company setup endpoints (plan §4.3–§4.4, `apps.companies.owner_api`,
 * `apps.inbox.owner_api` notification preferences, `apps.signin.owner_api` sessions). Written by
 * hand from the serializers: money and dates are strings.
 */
import type { Currency, Language, Money, PersonRef } from "@/api/types";
import type { CompanyFeature } from "@/core/features";

/** `GET/PATCH O settings/` */
export interface CompanySettings {
  id: number;
  name: string;
  slug: string;
  logo: string | null;
  timezone: string;
  default_language: Language;
  base_currency: Currency;
  /** True once the finance ledger has rows: the base currency can't change any more. */
  base_currency_locked: boolean;
  /** 0 = Monday … 6 = Sunday */
  workdays: number[];
  /** "HH:MM", company time */
  morning_report_at: string;
  evening_report_at: string;
  morning_digest: boolean;
  rejoin_cooldown_hours: number;
  owner_sees_personal_tasks: boolean;
  team_directory_phones: boolean;
  features: CompanyFeature[];
  setup_completed: boolean;
}

export type SettingsPatch = Partial<
  Pick<
    CompanySettings,
    | "name"
    | "timezone"
    | "default_language"
    | "base_currency"
    | "workdays"
    | "morning_report_at"
    | "evening_report_at"
    | "morning_digest"
    | "rejoin_cooldown_hours"
    | "owner_sees_personal_tasks"
    | "team_directory_phones"
  >
>;

/** `GET/PATCH O features/` */
export interface ModuleSwitch {
  key: CompanyFeature;
  label: string;
  enabled: boolean;
}

export interface Features {
  features: CompanyFeature[];
  modules: ModuleSwitch[];
}

/** One row of `GET O branches/` */
export interface Branch {
  id: number;
  name: string;
  code: string;
  address: string;
  phone: string;
  /** Decimal strings with 6 places, or null when not on the map. */
  latitude: string | null;
  longitude: string | null;
  /** Check-in radius in metres. */
  geofence_m: number;
  opens_at: string | null;
  closes_at: string | null;
  open_weekdays: number[];
  manager: PersonRef | null;
  cash_limit: Money | null;
  is_active: boolean;
  order: number;
  /** Approved members working there. */
  people: number;
}

export interface BranchInput {
  name: string;
  code: string;
  address: string;
  phone: string;
  latitude: string | null;
  longitude: string | null;
  geofence_m: number;
  opens_at: string | null;
  closes_at: string | null;
  open_weekdays: number[];
  manager_id: number | null;
  cash_limit: Money | null;
}

/** `GET O branches/managers/` */
export interface ManagerOption {
  id: number;
  name: string;
  position: string;
  branch: string;
  photo_url: string | null;
}

/** `GET O invite/` */
export interface Invite {
  /** Empty while the employee bot has no username. */
  link: string;
  start_param: string;
  bot_username: string;
  company: { name: string; logo: string | null };
  branches: string[];
  members: { approved: number; pending: number };
}

/** An id and a name, as the team link endpoints name branches, roles, positions and people. */
export interface Ref {
  id: number;
  name: string;
}

/** stopped > expired > full > active: the strongest reason wins. */
export type JoinLinkStatus = "active" | "full" | "expired" | "stopped";

/** One row of `GET O join-links/`: a team link that adds many people at once. */
export interface JoinLink {
  id: number;
  name: string;
  /** "https://t.me/<employee bot>?start=j_<code>"; empty while the bot has no username. */
  link: string;
  start_param: string;
  /** True: people are on the team at once. False: they become join requests. */
  auto_approve: boolean;
  branch: Ref | null;
  /** null: the company's default role at the moment someone joins (see `default_role`). */
  role: Ref | null;
  default_role: Ref | null;
  /** null: they pick their position; set: preselected in the app (they can change it). */
  position: Ref | null;
  /** null: no limit. */
  max_uses: number | null;
  /** Accounts finished through the link. */
  uses: number;
  /** ISO instant; null: no end date. */
  expires_at: string | null;
  /** False: stopped by hand. */
  is_active: boolean;
  status: JoinLinkStatus;
  /** A membership (person). */
  created_by: Ref | null;
  created_at: string;
  /** False when the viewer may not give its branch or role: read-only. */
  can_edit: boolean;
}

/** Someone who opened a team link. */
export interface JoinLinkPerson {
  /** Membership id (People › person page). */
  id: number;
  name: string;
  photo_url: string | null;
  position: Ref | null;
  status: "pending" | "approved" | "rejected" | "blocked" | "left" | "suspended";
  /** Finished creating the account. */
  onboarded: boolean;
  /** When they finished (or opened the link, while not onboarded). */
  joined_at: string;
}

/** `GET O join-links/{id}/`: the link and its people, newest first (at most 100). */
export interface JoinLinkDetail extends JoinLink {
  people: JoinLinkPerson[];
}

/** `POST O join-links/` */
export interface JoinLinkInput {
  /** 1–100 characters. */
  name: string;
  auto_approve?: boolean;
  branch_id?: number | null;
  /** A role with `can_assign` in `GET roles/`; null: the default role. */
  role_id?: number | null;
  /** An active position; null: they choose. */
  position_id?: number | null;
  /** 1–500; null: no limit. */
  max_uses?: number | null;
  /** In the future, at most 365 days ahead; null: no end date. */
  expires_at?: string | null;
}

/** `PATCH O join-links/{id}/`: `is_active: false` stops a link, `true` resumes it. */
export type JoinLinkPatch = Partial<JoinLinkInput> & { is_active?: boolean };

/** What a poster prints: the main invite link, or a team link with its branch and rule. */
export interface PosterTarget {
  link: string;
  company: { name: string; logo: string | null };
  /** The bot's username, printed under the code for people without a camera app. */
  bot: string;
  /** A team link's branch. */
  branch?: string | null;
  /** A team link that adds people without approval. */
  autoApprove?: boolean;
}

/** What the team link form needs from `GET O roles/`. */
export interface RoleOption {
  id: number;
  name: string;
  is_owner: boolean;
  is_default: boolean;
  /** The viewer may give it (anti-escalation). */
  can_assign: boolean;
}

/** What the team link form needs from `GET O positions/?active=true`. */
export interface PositionOption {
  id: number;
  name: string;
  is_active: boolean;
}

/** One row of `GET/PUT O notification-preferences/` */
export interface NotificationPreference {
  kind: string;
  label: string;
  audience: "owner" | "employee";
  severity: "info" | "warning" | "critical";
  /** False for kinds that live in "Needs you" (no in-app row to switch off). */
  in_app_available: boolean;
  in_app: boolean;
  telegram: boolean;
}

/** One row of `GET /owner/auth/sessions/` */
export interface DeviceSession {
  id: number;
  device: { label: string; browser: string; system: string; kind: "phone" | "tablet" | "desktop" };
  /** Masked: "213.230.x.x" */
  ip: string;
  created_at: string;
  last_seen_at: string;
  current: boolean;
}

export interface Revoked {
  revoked: number;
  signed_out: boolean;
}
