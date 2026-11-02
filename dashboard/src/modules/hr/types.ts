/**
 * Shapes of the HR endpoints (plan §4.10, apps.hr.owner_api), written by hand from the plan and the
 * serializers. Days are company-local "YYYY-MM-DD"; files come as short-lived signed links.
 * ID numbers (PINFL, passport, card) arrive masked ("AA•••••67") except from `people/{mid}/sensitive/`.
 */
import type { BranchRef, PersonRef } from "@/api/types";

// ─── Profile ───────────────────────────────────────────────────────────────

export type EmploymentType = "full_time" | "part_time" | "contractor" | "intern";
export type Gender = "male" | "female" | "";
export type PayoutMethod = "cash" | "card" | "bank";

export interface EmergencyContact {
  id: number;
  name: string;
  relation: string;
  phone: string;
}

export type EmergencyContactInput = Omit<EmergencyContact, "id">;

export interface Named {
  id: number;
  name: string;
}

/** `GET people/{mid}/profile/` (apps.hr.serializers.ProfileSerializer): IDs masked. */
export interface HrProfile {
  member: PersonRef;
  first_name: string;
  last_name: string;
  status: string;
  position: Named | null;
  department: Named | null;
  /** Their head: whom they report to. */
  manager: PersonRef | null;
  home_branch: BranchRef | null;
  employee_number: string;
  middle_name: string;
  birth_date: string | null;
  show_birthday: boolean;
  gender: Gender;
  hire_date: string | null;
  employment_type: EmploymentType;
  personal_phone: string;
  email: string;
  address: string;
  city: string;
  /** Masked ("••••••••••0045", "AA•••••67"), or "" when not recorded. */
  pinfl: string;
  passport: string;
  /** Someone else in the company has the same passport number on file. */
  passport_shared: boolean;
  /** The taxpayer number is not secret: it comes in full. */
  tin: string;
  payout_method: PayoutMethod;
  payout_card: string;
  terminated_on: string | null;
  termination_reason: string;
  termination_note: string;
  /** HR's own note; null without hr.manage. */
  notes: string | null;
  emergency_contacts: EmergencyContact[];
  can_edit: boolean;
  can_reveal: boolean;
}

/** What PATCH profile/ accepts. The ID fields are written in full (the server stores them encrypted). */
export interface ProfileInput {
  employee_number?: string;
  middle_name?: string;
  birth_date?: string | null;
  show_birthday?: boolean;
  gender?: Gender;
  hire_date?: string | null;
  employment_type?: EmploymentType;
  personal_phone?: string;
  email?: string;
  address?: string;
  city?: string;
  pinfl?: string;
  passport?: string;
  tin?: string;
  payout_method?: PayoutMethod;
  payout_card?: string;
  notes?: string;
}

/** `GET people/{mid}/sensitive/` (hr.sensitive, audited every time). */
export interface HrSensitive {
  member?: PersonRef;
  pinfl: string;
  passport: string;
  payout_card: string;
  tin?: string;
}

export type SensitiveField = "pinfl" | "passport" | "payout_card";

// ─── Documents ─────────────────────────────────────────────────────────────

export const DOCUMENT_KINDS = [
  "medical_book",
  "pharmacist_certificate",
  "pharmacy_diploma",
  "medical_diploma",
  "qualification_category",
  "state_registration",
  "medical_exam",
  "passport",
  "id_card",
  "military_id",
  "diploma",
  "work_book",
  "contract",
  "nda",
  "photo",
  "other",
] as const;
export type DocumentKind = (typeof DOCUMENT_KINDS)[number];

/** Kinds whose file and number need hr.sensitive (plan §3.11). */
export const ID_KINDS: readonly DocumentKind[] = ["passport", "id_card", "military_id"];

export type DocumentState = "valid" | "expiring" | "expired" | "no_expiry";

/** One row of `GET documents/` (apps.hr.serializers.DocumentSerializer). */
export interface HrDocument {
  id: number;
  member: PersonRef;
  position: string | null;
  home_branch: BranchRef | null;
  kind: DocumentKind;
  title: string;
  /** An ID's number is masked unless the viewer holds hr.sensitive; "" when there is none. */
  number: string;
  issued_on: string | null;
  expires_on: string | null;
  level: string;
  specialty: string;
  issuer: string;
  /** A signed link (minutes; every opening is audited), or null: no file, or not for this viewer. */
  file: string | null;
  has_file: boolean;
  /** There is a file this viewer may not open (an ID scan without hr.sensitive). */
  file_hidden: boolean;
  is_id: boolean;
  visible_to_employee: boolean;
  uploaded_by: string | null;
  verified: boolean;
  verified_by: string | null;
  verified_at: string | null;
  state: DocumentState;
  /** Days until it expires (negative once expired); null without an expiry. */
  days_left: number | null;
  created_at: string;
  can_edit: boolean;
}

export interface DocumentParams {
  member?: number;
  kind?: string[];
  state?: DocumentState;
  expiring_within?: number;
  verified?: boolean;
  /** Only each person's newest document per kind. */
  current?: boolean;
  branch?: number[];
  q?: string;
  /** expires_on, -expires_on, created_at or -created_at. */
  ordering?: string;
  page?: number;
  page_size?: number;
}

export interface DocumentInput {
  member_id: number;
  kind: DocumentKind;
  title: string;
  number: string;
  issued_on: string | null;
  expires_on: string | null;
  visible_to_employee: boolean;
  file?: File | null;
}

/** A required document: who must have which kind (position null = everyone). */
export interface RequiredDocument {
  id: number;
  kind: DocumentKind;
  position: Named | null;
  /** The level asked for ("higher", "college"…); "" for any. */
  level: string;
  /** Other kinds that satisfy it. */
  alternatives: DocumentKind[];
}

export type ComplianceStatus = "ok" | "expiring" | "expired" | "missing" | "unverified";

export interface ComplianceItem {
  kind: DocumentKind;
  status: ComplianceStatus;
  document_id: number | null;
  expires_on: string | null;
  level: string;
}

export interface ComplianceRow {
  member: PersonRef;
  position: Named | null;
  home_branch?: BranchRef | null;
  /** Only the kinds this person's position requires. */
  items: ComplianceItem[];
  /** Required documents missing or expired. */
  missing?: number;
  complete?: boolean;
}

/** `GET documents/compliance/`: the people × required kinds matrix. */
export interface Compliance {
  kinds: DocumentKind[];
  rows: ComplianceRow[];
  totals?: { people: number; complete: number; missing: number; expired: number; expiring: number; unverified: number };
}

// ─── Contracts ─────────────────────────────────────────────────────────────

export const CONTRACT_KINDS = ["indefinite", "fixed_term", "civil", "internship"] as const;
export type ContractKind = (typeof CONTRACT_KINDS)[number];
export type ContractStatus = "draft" | "active" | "ended" | "terminated";

export interface Contract {
  id: number;
  member: PersonRef;
  number: string;
  kind: ContractKind;
  status: ContractStatus;
  position: { id: number; name: string } | null;
  starts_on: string;
  ends_on: string | null;
  probation_until: string | null;
  probation_passed_at: string | null;
  weekly_hours: string | null;
  template: { id: number; name: string } | null;
  /** The generated PDF or the uploaded scan (signed link), or null. */
  file: string | null;
  acknowledged_at: string | null;
  terminated_on: string | null;
  termination_reason?: string;
  created_at: string;
}

export interface ContractParams {
  status?: ContractStatus[];
  member?: number;
  ending_within?: number;
  probation?: boolean;
  kind?: string[];
  q?: string;
  ordering?: string;
  page?: number;
  page_size?: number;
}

export interface ContractInput {
  member_id: number;
  kind: ContractKind;
  number: string;
  starts_on: string;
  ends_on: string | null;
  probation_until: string | null;
  weekly_hours: string | null;
  template_id: number | null;
  /** An uploaded scan instead of a template. */
  file?: File | null;
}

export type ContractAction = "activate" | "renew" | "terminate" | "pass-probation" | "extend-probation" | "generate-pdf";

// ─── Templates ─────────────────────────────────────────────────────────────

export type TemplateLanguage = "uz" | "ru" | "en";

export interface ContractTemplate {
  id: number;
  name: string;
  kind: ContractKind;
  language: TemplateLanguage;
  body: string;
  is_active: boolean;
  updated_at: string;
}

export type TemplateInput = Pick<ContractTemplate, "name" | "kind" | "language" | "body" | "is_active">;

/** `POST contract-templates/{id}/preview/`: the body filled in for one person. */
export interface TemplatePreview {
  html: string;
  /** Placeholders the person has no value for (shown empty in the text). */
  missing?: string[];
}

// ─── Celebrations ──────────────────────────────────────────────────────────

export interface Celebration {
  member: PersonRef;
  position: string | null;
  kind: "birthday" | "anniversary";
  day: string;
  /** Years at the company (anniversaries); never an age. */
  years: number | null;
}

// ─── Overview ──────────────────────────────────────────────────────────────

export interface ExpiringDocument {
  id: number;
  member: PersonRef;
  kind: DocumentKind;
  title: string;
  expires_on: string;
  /** Negative once expired. */
  days_left: number;
}

/** A contract's date on the overview: its end, or the end of its probation. */
export interface ContractDate {
  id: number;
  member: PersonRef;
  number: string;
  date: string;
  /** Negative once past. */
  days_left: number;
}

export interface UpcomingBirthday {
  member: PersonRef;
  date: string;
  days_until: number;
}

export interface UpcomingAnniversary extends UpcomingBirthday {
  years: number;
}

/** `GET overview/` (apps.hr.overview.OverviewSerializer). */
export interface HrOverview {
  as_of: string;
  headcount: { current: number; active: number; suspended: number; joined_30d: number; left_30d: number };
  /** Headcount at the end of each of the last 12 months (today for this one). */
  trend: Array<{ month: string; headcount: number; hired: number; left: number }>;
  documents: { expired: number; expiring: number; missing: number; unverified: number };
  expiring_documents: ExpiringDocument[];
  contracts: { active: number; drafts: number; ending: number; on_probation: number; without_contract: number };
  ending_contracts: ContractDate[];
  probation_endings: ContractDate[];
  birthdays: UpcomingBirthday[];
  anniversaries: UpcomingAnniversary[];
}

// ─── Settings ──────────────────────────────────────────────────────────────

export interface HrSettings {
  document_warn_days: number;
  contract_warn_days: number;
  probation_warn_days: number;
  celebrations_enabled: boolean;
  celebrate_anniversaries: boolean;
}
