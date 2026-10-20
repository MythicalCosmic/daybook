/**
 * Shapes of "Get started" and "New company" (plan §4.4, §13.2; `apps.companies.owner_api`).
 * Written by hand from the serializers.
 */
import type { Currency, Language } from "@/api/types";

/** One registered step of `GET O setup/`. `url` is a dashboard path relative to the company. */
export interface SetupStep {
  key: string;
  label: string;
  description: string;
  url: string;
  order: number;
  done: boolean;
}

export interface Setup {
  steps: SetupStep[];
  done: number;
  total: number;
  /** Hidden from the sidebar for everyone (dismissed, or finished and dismissed). */
  dismissed: boolean;
  can_dismiss: boolean;
}

/** `GET /owner/companies/new/` */
export interface NewCompanyInfo {
  mode: "open" | "code" | "off";
  allowed: boolean;
  needs_code: boolean;
  reason: string;
  owned: number;
  /** null: no limit (platform admins). */
  limit: number | null;
  parts: Array<{ key: string; label: string }>;
  sources: Array<{ id: number; name: string; parts: string[] }>;
}

/** `POST /owner/companies/` */
export interface NewCompanyInput {
  name: string;
  timezone: string;
  language: Language;
  base_currency: Currency;
  signup_code?: string;
  copy_from?: number | null;
  parts?: string[];
}

export interface CreatedCompany {
  id: number;
  name: string;
  slug: string;
  copied: Record<string, number>;
}
