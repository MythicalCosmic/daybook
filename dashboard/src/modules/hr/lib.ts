/**
 * The HR module's plain logic, kept out of the pages so it is tested on its own: who may do what,
 * masked IDs and their reveal, a document's expiry state, the list filters as API params, the
 * compliance matrix, contract actions by status, and the template placeholders.
 */
import type { PersonRef } from "@/api/types";
import type { StatusTone } from "@/components/StatusPill.vue";
import type { FilterValues } from "@/components/filters";
import { diffDays } from "@/lib/dates";

import {
  ID_KINDS,
  type ComplianceRow,
  type ComplianceStatus,
  type Compliance,
  type Contract,
  type ContractAction,
  type ContractParams,
  type ContractStatus,
  type DocumentKind,
  type DocumentParams,
  type DocumentState,
  type HrOverview,
  type HrProfile,
  type HrSensitive,
  type SensitiveField,
} from "./types";

// ─── Access ────────────────────────────────────────────────────────────────

export interface HrAccess {
  view: boolean;
  manage: boolean;
  sensitive: boolean;
}

/** What the viewer may do here; anything without `manage` is read-only. */
export function hrAccess(can: (perm: "hr.view" | "hr.manage" | "hr.sensitive") => boolean): HrAccess {
  const manage = can("hr.manage");
  return { view: manage || can("hr.view"), manage, sensitive: can("hr.sensitive") };
}

// ─── Masked IDs ────────────────────────────────────────────────────────────

const MASK = /[•*]/;

/** The server masks IDs with bullets ("AA•••••67"); an empty value means none was recorded. */
export function isMasked(value: string | null | undefined): boolean {
  return !!value && MASK.test(value);
}

export const SENSITIVE_FIELDS: readonly SensitiveField[] = ["pinfl", "passport", "payout_card"];

/**
 * What an ID field shows: the full number once revealed (hr.sensitive, audited on the server),
 * else the masked one. `canReveal` says whether the reveal button makes sense for it.
 */
export function idDisplay(profile: Pick<HrProfile, SensitiveField>, field: SensitiveField, revealed: HrSensitive | null, mayReveal: boolean): { text: string; revealed: boolean; canReveal: boolean } {
  const masked = profile[field] ?? "";
  if (!masked) return { text: "", revealed: false, canReveal: false };
  const full = revealed?.[field];
  if (full) return { text: full, revealed: true, canReveal: false };
  return { text: masked, revealed: false, canReveal: mayReveal && isMasked(masked) };
}

/**
 * Checks the ID numbers typed into the profile before they go to the server (which checks again):
 * PINFL 14 digits, passport two letters and seven digits, TIN 9 digits, a card 16 to 19 digits.
 * Spaces are ignored; an empty field means "keep what is stored". Returns the cleaned values and
 * the fields at fault.
 */
export function cleanIds(input: { pinfl?: string; passport?: string; tin?: string; payout_card?: string }): {
  values: { pinfl?: string; passport?: string; tin?: string; payout_card?: string };
  errors: Array<"pinfl" | "passport" | "tin" | "payout_card">;
} {
  const values: { pinfl?: string; passport?: string; tin?: string; payout_card?: string } = {};
  const errors: Array<"pinfl" | "passport" | "tin" | "payout_card"> = [];
  const rules = { pinfl: /^\d{14}$/, passport: /^[A-Z]{2}\d{7}$/, tin: /^\d{9}$/, payout_card: /^\d{16,19}$/ } as const;
  for (const field of ["pinfl", "passport", "tin", "payout_card"] as const) {
    const raw = (input[field] ?? "").replace(/[\s-]/g, "");
    if (!raw) continue;
    const value = field === "passport" ? raw.toUpperCase() : raw;
    if (rules[field].test(value)) values[field] = value;
    else errors.push(field);
  }
  return { values, errors };
}

/** Groups digits for reading ("8600 1234 5678 9012"); masked or short values are left alone. */
export function groupDigits(value: string, size = 4): string {
  if (isMasked(value) || !/^\d+$/.test(value) || value.length <= size) return value;
  return value.replace(new RegExp(`(\\d{${size}})(?=\\d)`, "g"), "$1 ");
}

/** A document's file and number are hidden from viewers without hr.sensitive for ID kinds. */
export function needsSensitive(kind: DocumentKind): boolean {
  return ID_KINDS.includes(kind);
}

export type KindGroup = "qualification" | "identity" | "other";

/** How the kind pickers group the kinds: what a pharmacy checks most comes first. */
export function kindGroup(kind: DocumentKind): KindGroup {
  if (ID_KINDS.includes(kind)) return "identity";
  if (["medical_book", "pharmacist_certificate", "pharmacy_diploma", "medical_diploma", "qualification_category", "state_registration", "medical_exam"].includes(kind)) return "qualification";
  return "other";
}

// ─── Expiry ────────────────────────────────────────────────────────────────

export function documentState(expiresOn: string | null, today: string, warnDays: number): DocumentState {
  if (!expiresOn) return "no_expiry";
  const left = diffDays(today, expiresOn);
  if (left < 0) return "expired";
  return left <= warnDays ? "expiring" : "valid";
}

export const DOCUMENT_STATE_TONES: Record<DocumentState, StatusTone> = { valid: "success", expiring: "warning", expired: "danger", no_expiry: "neutral" };

/** Days from today to `day` (negative when it has passed). */
export function daysUntil(day: string, today: string): number {
  return diffDays(today, day);
}

// ─── Overview ──────────────────────────────────────────────────────────────

/**
 * The headcount tile: people now, and 30 days ago (now, less who joined since, plus who left
 * since) for the change; the 12-month trend as its sparkline.
 */
export function headcountKpi(overview: Pick<HrOverview, "headcount" | "trend">): { value: number; previous: number; spark: number[] } {
  const h = overview.headcount;
  return { value: h.current, previous: h.current - h.joined_30d + h.left_30d, spark: overview.trend.map((point) => point.headcount) };
}

export interface WeekCelebration {
  kind: "birthday" | "anniversary";
  member: PersonRef;
  date: string;
  days_until: number;
  years: number | null;
}

/** Birthdays and work anniversaries of the coming week in one list, soonest first. */
export function weekCelebrations(overview: Pick<HrOverview, "birthdays" | "anniversaries">): WeekCelebration[] {
  return [
    ...overview.birthdays.map((row) => ({ kind: "birthday" as const, member: row.member, date: row.date, days_until: row.days_until, years: null })),
    ...overview.anniversaries.map((row) => ({ kind: "anniversary" as const, member: row.member, date: row.date, days_until: row.days_until, years: row.years })),
  ].sort((a, b) => a.days_until - b.days_until || a.member.name.localeCompare(b.member.name));
}

// ─── Filters → params ──────────────────────────────────────────────────────

const asList = (value: unknown): string[] => (Array.isArray(value) ? value.map(String) : typeof value === "string" && value ? [value] : []);
const asNumber = (value: unknown): number | undefined => {
  const n = Number(Array.isArray(value) ? value[0] : value);
  return Number.isInteger(n) && n > 0 ? n : undefined;
};
const asBoolean = (value: unknown): boolean | undefined => (value === true || value === "true" ? true : value === false || value === "false" ? false : undefined);

const STATES: readonly DocumentState[] = ["valid", "expiring", "expired", "no_expiry"];

/**
 * The Documents filters as the API's query: "state" is a chip (expiring inside the company's
 * warning window, or expired; the server knows the window), "kind" many kinds, "verified" yes/no,
 * "member" one person.
 */
export function documentParams(values: FilterValues, search: string): DocumentParams {
  const params: DocumentParams = {};
  const state = asList(values.state)[0] as DocumentState | undefined;
  if (state && STATES.includes(state)) params.state = state;
  const kinds = asList(values.kind);
  if (kinds.length) params.kind = kinds;
  const verified = asBoolean(values.verified);
  if (verified !== undefined) params.verified = verified;
  const member = asNumber(values.member);
  if (member) params.member = member;
  if (search.trim()) params.q = search.trim();
  return params;
}

export type ContractView = "active" | "draft" | "ended" | "all";

const VIEW_STATUSES: Record<ContractView, ContractStatus[] | undefined> = {
  active: ["active"],
  draft: ["draft"],
  ended: ["ended", "terminated"],
  all: undefined,
};

/** The Contracts tab and chips as the API's query. */
export function contractParams(view: ContractView, values: FilterValues, search: string, warnDays: number): ContractParams {
  const params: ContractParams = {};
  const status = VIEW_STATUSES[view];
  if (status) params.status = status;
  if (asBoolean(values.ending)) params.ending_within = warnDays;
  if (asBoolean(values.probation)) params.probation = true;
  const kinds = asList(values.kind);
  if (kinds.length) params.kind = kinds;
  if (search.trim()) params.q = search.trim();
  return params;
}

// ─── Compliance ────────────────────────────────────────────────────────────

/** Statuses that count as a gap (something to fix). */
export const GAPS: readonly ComplianceStatus[] = ["missing", "expired", "expiring", "unverified"];

export interface MatrixRow extends ComplianceRow {
  /** Cell per column kind; null where the person's position doesn't require it. */
  byKind: Record<string, ComplianceStatus | null>;
  /** The document behind each cell, when there is one (it opens on a click). */
  documents: Record<string, number | null>;
  /** Kinds to fix, worst first (missing and expired before expiring and unverified). */
  gaps: Array<{ kind: DocumentKind; status: ComplianceStatus; document_id?: number | null }>;
}

export interface MatrixGroup {
  key: string;
  position: string | null;
  rows: MatrixRow[];
}

export interface Matrix {
  kinds: DocumentKind[];
  groups: MatrixGroup[];
  people: number;
  withGaps: number;
  /** Gaps per kind (the column header's count). */
  gapsByKind: Record<string, number>;
}

const GAP_ORDER: Record<ComplianceStatus, number> = { missing: 0, expired: 1, expiring: 2, unverified: 3, ok: 4 };

/**
 * People × required kinds, grouped by position (positions alphabetical, "no position" last), each
 * row with its gaps; `onlyGaps` keeps only people who lack something ("who lacks what").
 */
export function shapeCompliance(data: Compliance | null | undefined, options: { onlyGaps?: boolean; collator?: Intl.Collator } = {}): Matrix {
  const collator = options.collator ?? new Intl.Collator();
  const kinds = [...(data?.kinds ?? [])];
  const gapsByKind: Record<string, number> = Object.fromEntries(kinds.map((kind) => [kind, 0]));
  const groups = new Map<string, MatrixGroup>();
  let people = 0;
  let withGaps = 0;
  for (const row of data?.rows ?? []) {
    people += 1;
    const byKind: Record<string, ComplianceStatus | null> = Object.fromEntries(kinds.map((kind) => [kind, null]));
    const documents: Record<string, number | null> = {};
    const gaps: MatrixRow["gaps"] = [];
    for (const cell of row.items) {
      byKind[cell.kind] = cell.status;
      documents[cell.kind] = cell.document_id ?? null;
      if (GAPS.includes(cell.status)) {
        gaps.push({ kind: cell.kind, status: cell.status, document_id: cell.document_id ?? null });
        gapsByKind[cell.kind] = (gapsByKind[cell.kind] ?? 0) + 1;
      }
    }
    gaps.sort((a, b) => GAP_ORDER[a.status] - GAP_ORDER[b.status]);
    if (gaps.length) withGaps += 1;
    if (options.onlyGaps && !gaps.length) continue;
    const key = row.position ? `p${row.position.id}` : "none";
    const group = groups.get(key) ?? { key, position: row.position?.name ?? null, rows: [] };
    group.rows.push({ ...row, byKind, documents, gaps });
    groups.set(key, group);
  }
  const sorted = [...groups.values()].sort((a, b) => (a.position === null ? 1 : b.position === null ? -1 : collator.compare(a.position, b.position)));
  for (const group of sorted) group.rows.sort((a, b) => b.gaps.length - a.gaps.length || collator.compare(a.member.name, b.member.name));
  return { kinds, groups: sorted, people, withGaps, gapsByKind };
}

// ─── Contracts ─────────────────────────────────────────────────────────────

export const CONTRACT_TONES: Record<ContractStatus, StatusTone> = { draft: "neutral", active: "success", ended: "info", terminated: "danger" };

/** Probation still running: a date set and not passed yet. */
export function onProbation(contract: Pick<Contract, "status" | "probation_until" | "probation_passed_at">): boolean {
  return contract.status === "active" && !!contract.probation_until && !contract.probation_passed_at;
}

/**
 * What can be done to a contract now (plan §3.11): a draft is activated; an active one is
 * renewed, terminated, its probation passed or extended; an ended one renewed; a terminated one is
 * final. A PDF is generated from a template while it is a draft or active. Nothing without hr.manage.
 */
export function contractActions(contract: Pick<Contract, "status" | "kind" | "probation_until" | "probation_passed_at" | "template">, canManage: boolean): ContractAction[] {
  if (!canManage) return [];
  const actions: ContractAction[] = [];
  switch (contract.status) {
    case "draft":
      actions.push("activate");
      break;
    case "active":
      if (onProbation(contract)) actions.push("pass-probation", "extend-probation");
      if (contract.kind !== "indefinite") actions.push("renew");
      actions.push("terminate");
      break;
    case "ended":
      actions.push("renew");
      break;
    case "terminated":
      break;
  }
  if (contract.template && (contract.status === "draft" || contract.status === "active")) actions.push("generate-pdf");
  return actions;
}

/** A fixed-term contract needs an end; an end can't come before the start. Returns the field at fault. */
export function contractDatesProblem(input: { kind: string; starts_on: string | null; ends_on: string | null; probation_until: string | null }): "starts_on" | "ends_on" | "probation_until" | null {
  if (!input.starts_on) return "starts_on";
  if (input.kind === "fixed_term" && !input.ends_on) return "ends_on";
  if (input.ends_on && input.ends_on < input.starts_on) return "ends_on";
  if (input.probation_until && (input.probation_until < input.starts_on || (input.ends_on && input.probation_until > input.ends_on))) return "probation_until";
  return null;
}

// ─── Template placeholders ─────────────────────────────────────────────────

/** The fixed list the server fills (plan §3.11); `salary_text` only for a renderer with payroll.view. */
export const PLACEHOLDERS = [
  "employee_full_name",
  "position",
  "branch",
  "starts_on",
  "ends_on",
  "probation_until",
  "weekly_hours",
  "salary_text",
  "company_name",
  "company_tin",
  "today",
] as const;
export type Placeholder = (typeof PLACEHOLDERS)[number];

export const token = (key: string) => `{{${key}}}`;

const TOKEN = /\{\{\s*([a-z_]+)\s*\}\}/g;

/** Placeholders a body uses, in order of first use. */
export function placeholdersIn(body: string): string[] {
  const seen: string[] = [];
  for (const match of body.matchAll(TOKEN)) if (!seen.includes(match[1]!)) seen.push(match[1]!);
  return seen;
}

/** Placeholders the server won't fill (typos): they would print as written. */
export function unknownPlaceholders(body: string): string[] {
  return placeholdersIn(body).filter((key) => !(PLACEHOLDERS as readonly string[]).includes(key));
}

/**
 * Puts `{{key}}` in place of the selection of a plain text (the HTML source view), with a space
 * before it when it would stick to a word; returns the new text and where the caret goes.
 */
export function insertPlaceholder(text: string, start: number, end: number, key: string): { text: string; caret: number } {
  const from = Math.max(0, Math.min(start, text.length));
  const to = Math.max(from, Math.min(end, text.length));
  const before = text.slice(0, from);
  const glue = before && /[\p{L}\p{N}]$/u.test(before) ? " " : "";
  const inserted = glue + token(key);
  return { text: before + inserted + text.slice(to), caret: from + inserted.length };
}
