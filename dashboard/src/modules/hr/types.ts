/**
 * Shapes of the HR endpoints (plan §4.10, apps.hr.owner_api), written by hand from the plan and the
 * serializers. Days are company-local "YYYY-MM-DD"; files come as short-lived signed links.
 * ID numbers (PINFL, passport, card) arrive masked ("AA•••••67") except from `people/{mid}/sensitive/`.
 */
import type { PersonRef, Summary } from "@/api/types";

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

/** `GET people/{mid}/profile/`: IDs masked. */
export interface HrProfile {
  member: PersonRef;
  position: string | null;
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
  /** Masked, or "" when not recorded. */
  pinfl: string;
  passport: string;
  tin: string;
  payout_method: PayoutMethod;
  payout_card: string;
  terminated_on: string | null;
  termination_reason: string;
  /** HR's own note; only for hr.manage. */
  notes?: string;
  emergency_contacts: EmergencyContact[];
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
  pinfl: string;
  passport: string;
  payout_card: string;
}

export type SensitiveField = keyof HrSensitive;

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

/** One row of `GET documents/`. */
export interface HrDocument {
  id: number;
  member: PersonRef;
  position: string | null;
  kind: DocumentKind;
  title: string;
  /** Masked unless the viewer holds hr.sensitive; "" when there is none. */
  number: string;
  issued_on: string | null;
  expires_on: string | null;
  level?: string;
  specialty?: string;
  issuer?: string;
  /** A signed link (minutes), or null when there is no file or the viewer may not open it. */
  file: string | null;
  file_name?: string;
  visible_to_employee: boolean;
  verified_at: string | null;
  verified_by: string | null;
  uploaded_by: string | null;
  created_at: string;
}

export interface DocumentParams {
  member?: number;
  kind?: string[];
  expiring_within?: number;
  expired?: boolean;
  verified?: boolean;
  q?: string;
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
  position: { id: number; name: string } | null;
  level?: string;
  alternatives?: DocumentKind[];
}

export type ComplianceStatus = "ok" | "expiring" | "expired" | "missing" | "unverified";

export interface ComplianceCell {
  kind: DocumentKind;
  status: ComplianceStatus;
  document_id?: number | null;
  expires_on?: string | null;
}

export interface ComplianceRow {
  member: PersonRef;
  position: { id: number; name: string } | null;
  /** Only the kinds this person's position requires. */
  cells: ComplianceCell[];
}

/** `GET documents/compliance/`: the people × required kinds matrix. */
export interface Compliance {
  kinds: DocumentKind[];
  rows: ComplianceRow[];
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
  days_left: number;
}

export interface EndingContract {
  id: number;
  member: PersonRef;
  kind: ContractKind;
  ends_on: string;
  days_left: number;
}

export interface ProbationEnding {
  id: number;
  member: PersonRef;
  probation_until: string;
  days_left: number;
}

/** `GET overview/` */
export interface HrOverview {
  today: string;
  headcount: Summary<"headcount">;
  documents: { expiring: number; expired: number; items: ExpiringDocument[] };
  contracts: { ending: number; items: EndingContract[] };
  probation: { ending: number; items: ProbationEnding[] };
  birthdays: Celebration[];
  warn_days: { documents: number; contracts: number; probation: number };
}

// ─── Settings ──────────────────────────────────────────────────────────────

export interface HrSettings {
  document_warn_days: number;
  contract_warn_days: number;
  probation_warn_days: number;
  celebrations_enabled: boolean;
  celebrate_anniversaries: boolean;
}
