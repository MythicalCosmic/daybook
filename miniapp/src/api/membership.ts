/**
 * Company and membership facts that phase 2 adds to `me/` (PLAN-OWNER §3.2, §13.4), read in one
 * place so feature folders don't each cast the generated types.
 *
 * Until the lead regenerates `schema.d.ts`, the generated `Membership` lacks these fields; once it
 * has them the casts below are plain no-ops and every caller keeps working unchanged. When a field
 * is missing (an older server), each helper falls back to the safe answer named in its comment.
 */
import type { Membership } from "./types";

/** Modules an owner switches on per company (`companies.Feature`): `Company.features` is the only switch. */
export const MODULES = ["finance", "sales", "stock", "attendance", "hr", "payroll", "ai", "recognition"] as const;
export type Module = (typeof MODULES)[number];

export type BranchBrief = { id: number; name: string };

type CompanyFacts = {
  features?: readonly string[];
  owner_sees_personal_tasks?: boolean;
  team_directory_phones?: boolean;
  base_currency?: string;
};

type MembershipFacts = { home_branch?: BranchBrief | null; branch_ids?: readonly number[]; suspended_until?: string | null };

type HasCompany = { company: Membership["company"] };

const companyOf = (member: HasCompany) => member.company as Membership["company"] & CompanyFacts;

/** Whether the company has switched `module` on. Missing list: off (nothing shows by accident). */
export function hasModule(member: HasCompany, module: Module): boolean {
  return companyOf(member).features?.includes(module) ?? false;
}

/** Whether owners can read personal tasks. Missing: yes, so the add sheet never under-warns. */
export function ownerSeesPersonalTasks(member: HasCompany): boolean {
  return companyOf(member).owner_sees_personal_tasks ?? true;
}

/** Whether colleagues see each other's phone numbers. Missing: no, so numbers never leak. */
export function teamDirectoryPhones(member: HasCompany): boolean {
  return companyOf(member).team_directory_phones ?? false;
}

/** The company's base currency for money without one of its own. Missing: UZS. */
export function baseCurrency(member: HasCompany): string {
  return companyOf(member).base_currency ?? "UZS";
}

/** The branch the person mostly works at, if the company has branches set up. */
export function homeBranch(member: Membership): BranchBrief | null {
  return (member as Membership & MembershipFacts).home_branch ?? null;
}

/** The branches the person belongs to (empty: not tied to a branch). */
export function branchIds(member: Membership): readonly number[] {
  return (member as Membership & MembershipFacts).branch_ids ?? [];
}

/** Whether the membership is suspended (§13.4): the app shows the "Access paused" screen. */
export function isSuspended(member: Pick<Membership, "status">): boolean {
  return (member.status as string) === "suspended";
}

/** The last day of a suspension ("2026-11-12"), or null while it runs until reinstated. */
export function suspendedUntil(member: Membership): string | null {
  return (member as Membership & MembershipFacts).suspended_until ?? null;
}
