/**
 * Pure helpers of the pharmacist coverage views (plan §14.9): the day bar's covered and uncovered
 * stretches, the roster link, the levels a document kind takes. Instants come from the API with the
 * company's offset; positions are computed on absolute time, so the browser's zone never matters.
 */
import { addDays, startOfWeek } from "@/lib/dates";

import type { CoverageBranch, CoverageDay, CoverageGap, CoverageParams, DocumentKind, DocumentLevel } from "./types";

export interface Segment {
  /** Fractions of the day's open window, 0 to 1. */
  from: number;
  to: number;
  /** covered: enough qualified pharmacists; gap: none; short: some, fewer than needed. */
  tone: "covered" | "gap" | "short";
}

/** The day's open window split into covered and uncovered stretches. */
export function daySegments(day: Pick<CoverageDay, "opens" | "closes" | "gaps">): Segment[] {
  if (!day.opens || !day.closes) return [];
  const start = Date.parse(day.opens);
  const span = Date.parse(day.closes) - start;
  if (!(span > 0)) return [];
  const holes = day.gaps
    .map((gap): Segment => ({
      from: Math.max(0, (Date.parse(gap.start) - start) / span),
      to: Math.min(1, (Date.parse(gap.end) - start) / span),
      tone: gap.have > 0 ? "short" : "gap",
    }))
    .filter((segment) => segment.to > segment.from)
    .sort((a, b) => a.from - b.from);
  const out: Segment[] = [];
  let at = 0;
  for (const hole of holes) {
    if (hole.from > at) out.push({ from: at, to: hole.from, tone: "covered" });
    out.push(hole);
    at = Math.max(at, hole.to);
  }
  if (at < 1) out.push({ from: at, to: 1, tone: "covered" });
  return out;
}

/** The week shown: Monday to Sunday of `day`. */
export function weekParams(week: string, branchId?: number | null, drafts = false): CoverageParams {
  const from = startOfWeek(week);
  return { from, to: addDays(from, 6), ...(branchId ? { branch: [branchId] } : {}), ...(drafts ? { drafts: true } : {}) };
}

/** "Fix in roster": the roster of `branchId` at the week of `day`. */
export function rosterLink(companyId: number, branchId: number, day: string): string {
  return `/c/${companyId}/attendance/roster?branch=${branchId}&week=${startOfWeek(day)}`;
}

/** Whole hours and a half: 300 minutes → 5, 90 → 1.5. */
export function hoursOf(minutes: number): number {
  return Math.round(minutes / 30) / 2;
}

export interface CoverageTotals {
  /** Pharmacies checked (open at least once in the period). */
  branches: number;
  gaps: number;
  minutes: number;
  /** Pharmacies with at least one gap. */
  short: number;
}

export function coverageTotals(branches: readonly CoverageBranch[]): CoverageTotals {
  const open = branches.filter((branch) => branch.days.some((day) => day.opens));
  return {
    branches: open.length,
    gaps: open.reduce((sum, branch) => sum + branch.gaps.length, 0),
    minutes: open.reduce((sum, branch) => sum + branch.gap_minutes, 0),
    short: open.filter((branch) => branch.gaps.length > 0).length,
  };
}

/** The period's gaps of every branch, soonest first, with the branch beside each. */
export function allGaps(branches: readonly CoverageBranch[]): Array<CoverageGap & { branchName: string }> {
  return branches
    .flatMap((branch) => branch.gaps.map((gap) => ({ ...gap, branchName: branch.branch.name })))
    .sort((a, b) => Date.parse(a.start) - Date.parse(b.start) || a.branchName.localeCompare(b.branchName));
}

/** The day (company-local "YYYY-MM-DD") an instant from the API starts on: its own date part. */
export function dayOfInstant(iso: string): string {
  return iso.slice(0, 10);
}

const DIPLOMAS: readonly DocumentKind[] = ["diploma", "pharmacy_diploma", "medical_diploma"];

/** The levels a kind of document takes (a diploma's or a qualification category's); none for the rest. */
export function levelsFor(kind: DocumentKind | null | undefined): DocumentLevel[] {
  if (kind && DIPLOMAS.includes(kind)) return ["higher", "college"];
  if (kind === "qualification_category") return ["highest", "first", "second"];
  return [];
}

/** Kinds whose specialty and issuer are worth recording (education and qualification). */
export function hasQualificationFields(kind: DocumentKind | null | undefined): boolean {
  return !!kind && (DIPLOMAS.includes(kind) || ["pharmacist_certificate", "qualification_category", "state_registration"].includes(kind));
}
