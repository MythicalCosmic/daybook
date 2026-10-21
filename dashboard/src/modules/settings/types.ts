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
