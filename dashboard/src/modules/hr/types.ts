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
  /** A diploma's level (higher, college) or a qualification category (highest, first, second). */
  level?: DocumentLevel | "";
  specialty?: string;
  issuer?: string;
  visible_to_employee: boolean;
  file?: File | null;
}

export const DOCUMENT_LEVELS = ["higher", "college", "highest", "first", "second"] as const;
export type DocumentLevel = (typeof DOCUMENT_LEVELS)[number];

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

/** What the viewer may do with a contract now (the server decides; the dashboard shows buttons). */
export interface ContractActionFlags {
  edit: boolean;
  delete: boolean;
  activate: boolean;
  terminate: boolean;
  end: boolean;
  renew: boolean;
  pass_probation: boolean;
  extend_probation: boolean;
  generate_pdf: boolean;
}

/** One row of `GET contracts/` (apps.hr.serializers.ContractSerializer). */
export interface Contract {
  id: number;
  member: PersonRef;
  home_branch: BranchRef | null;
  number: string;
  kind: ContractKind;
  status: ContractStatus;
  position: Named | null;
  starts_on: string;
  ends_on: string | null;
  probation_until: string | null;
  probation_passed_at: string | null;
  on_probation: boolean;
  weekly_hours: string | null;
  template: Named | null;
  /** The generated PDF or the uploaded scan (signed link), or null: none, or not for this viewer. */
  file: string | null;
  has_file: boolean;
  /** There is a file this viewer may not open (it shows the pay: payroll.view only). */
  file_hidden: boolean;
  /** The file is a scan of a paper contract, not printed from a template. */
  file_is_scan: boolean;
  pdf_generated_at: string | null;
  acknowledged_at: string | null;
  terminated_on: string | null;
  termination_reason: string;
  note: string;
  /** Days until it ends; null if open-ended. */
  days_left: number | null;
  probation_days_left: number | null;
  created_by: string | null;
  created_at: string;
  actions: ContractActionFlags;
}

export interface ContractParams {
  status?: ContractStatus[];
  member?: number;
  /** In force, ending within N days. */
  ending_within?: number;
  /** Probation ending within N days. */
  probation_within?: number;
  acknowledged?: boolean;
  kind?: string[];
  q?: string;
  /** starts_on, -starts_on, ends_on or -ends_on. */
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

export type ContractAction = "activate" | "renew" | "end" | "terminate" | "pass-probation" | "extend-probation" | "generate-pdf";

// ─── Templates ─────────────────────────────────────────────────────────────

export type TemplateLanguage = "uz" | "ru" | "en";

export interface ContractTemplate {
  id: number;
  name: string;
  /** "" when it fits any kind. */
  kind: ContractKind | "";
  language: TemplateLanguage;
  body: string;
  is_active: boolean;
  /** Contracts printed from it. */
  contracts: number;
  updated_at: string;
}

export type TemplateInput = Pick<ContractTemplate, "name" | "kind" | "language" | "body" | "is_active">;

/** `POST contract-templates/{id}/preview/` (or `contract-templates/preview/` for unsaved text). */
export interface TemplatePreview {
  /** The filled-in text (safe HTML). */
  html: string;
  /** Placeholders with nothing to fill in for this person. */
  empty: string[];
  has_salary: boolean;
}

// ─── Celebrations ──────────────────────────────────────────────────────────

/** One row of `GET celebrations/?from&to`. */
export interface Celebration {
  member: PersonRef;
  kind: "birthday" | "anniversary";
  date: string;
  /** Years with the company (anniversaries); never an age. */
  years: number | null;
  /** Negative once past. */
  days_until: number;
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
  /** Pharmacist coverage (plan §14.9); the positions are chosen through `coverage/pharmacists/`. */
  coverage_enabled?: boolean;
  coverage_min?: number;
  coverage_needs_documents?: boolean;
  coverage_alert_minutes?: number;
  coverage_days?: number;
  unqualified_seller_alert?: boolean;
  /** Read only: who counts as a pharmacist on duty. */
  pharmacist_positions?: Named[];
}

// ─── Pharmacist coverage (plan §14.9) ─────────────────────────────────────

/** ok, or why nothing was checked: off (HR or the rule), setup (no pharmacists chosen), no_roster (attendance off). */
export type CoverageState = "ok" | "off" | "setup" | "no_roster";
/** Why someone in a pharmacist position doesn't count that day. */
export type CoverageReason = "not_approved" | "not_pharmacist" | "missing" | "expired" | "unverified";
export type PharmacistRole = "head" | "senior" | "pharmacist" | "custom";

/** Part of a pharmacy's open hours with fewer qualified pharmacists planned than it needs. */
export interface CoverageGap {
  branch_id: number;
  /** ISO instants in the company's timezone. */
  start: string;
  end: string;
  minutes: number;
  have: number;
  need: number;
}

/** A shift of someone in a pharmacist position, and whether it counts. */
export interface CoverageShift {
  shift_id: number;
  member: PersonRef;
  position: string | null;
  start: string;
  end: string;
  published: boolean;
  counts: boolean;
  /** Why not; null for viewers without hr.view. */
  reason: CoverageReason | null;
  kinds: DocumentKind[];
}

export interface CoverageDay {
  date: string;
  opens: string | null;
  closes: string | null;
  /** Why it is closed that day. */
  closed: "weekday" | "holiday" | "no_hours" | null;
  shifts: CoverageShift[];
  gaps: CoverageGap[];
}

export interface CoverageBranch {
  branch: BranchRef;
  open_24h: boolean;
  opens_at: string | null;
  closes_at: string | null;
  days: CoverageDay[];
  /** The period's gaps, a night across midnight as one. */
  gaps: CoverageGap[];
  /** Shifts of anyone planned there in the period. */
  shifts: number;
  gap_minutes: number;
}

/** `GET coverage/?from&to&branch&drafts`. */
export interface Coverage {
  state: CoverageState;
  start: string;
  end: string;
  need: number;
  drafts: boolean;
  branches: CoverageBranch[];
}

export interface CoverageParams {
  from: string;
  to: string;
  branch?: number[];
  drafts?: boolean;
}

export interface LiveGap {
  branch: BranchRef;
  since: string;
  minutes: number;
  have: number;
  need: number;
  /** Checked in, but not counting. */
  checked_in: PersonRef[];
}

/** `GET coverage/live/`: pharmacies open now without enough qualified pharmacists checked in. */
export interface LiveCoverage {
  state: CoverageState;
  at: string;
  gaps: LiveGap[];
}

export interface PharmacistPosition {
  position: Named;
  /** null: not a pharmacist; custom: counts, with documents changed by hand. */
  role: PharmacistRole | null;
  people: number;
  required: Array<{ kind: DocumentKind; level: string; alternatives: DocumentKind[] }>;
}

export interface Pharmacists {
  positions: PharmacistPosition[];
}
