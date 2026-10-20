import type { components } from "./schema";

/** The permissions today's generated schema knows (`members/permissions.py` before phase 2). */
export type SchemaPerm = components["schemas"]["PermissionsEnum"];

/**
 * Phase 2 permission codenames (PLAN-OWNER §5 and §13), hand-written here until the lead
 * regenerates `schema.d.ts` at integration. Keep this list in the same order as the plan.
 */
export const PHASE2_PERMS = [
  // §5: owner console, money, HR and AI
  "dashboard.access",
  "company.settings",
  "audit.view",
  "data.export",
  "branches.all",
  "sales.view",
  "sales.operate",
  "sales.manage",
  "stock.manage",
  "finance.view",
  "finance.record",
  "finance.manage",
  "finance.approve",
  "finance.claim",
  "hr.view",
  "hr.manage",
  "hr.sensitive",
  "attendance.view",
  "attendance.manage",
  "time_off.manage",
  "payroll.view",
  "payroll.propose",
  "payroll.manage",
  "payroll.finalize",
  "payroll.pay",
  "ai.use",
  "ai.configure",
  // §13: projects, people lifecycle, knowledge base, CRM and invoices
  "projects.view_all",
  "projects.manage",
  "projects.time_view",
  "hr.discipline",
  "hr.suspend",
  "hr.terminate",
  "org.manage",
  "assets.manage",
  "hiring.manage",
  "reviews.manage",
  "knowledge.manage",
  "crm.view",
  "crm.manage",
  "invoices.manage",
] as const;

export type Phase2Perm = (typeof PHASE2_PERMS)[number];

/** Every permission codename a mini app screen may check. */
export type Perm = SchemaPerm | Phase2Perm;

type HasPermissions = { permissions: readonly string[] };

/**
 * Whether the membership holds `perm`. The server expands owner roles into every permission,
 * so this is a plain lookup; the server still checks every request.
 */
export function can(member: HasPermissions, perm: Perm): boolean {
  return member.permissions.includes(perm);
}

export function canAny(member: HasPermissions, perms: readonly Perm[]): boolean {
  return perms.some((perm) => can(member, perm));
}

export function canAll(member: HasPermissions, perms: readonly Perm[]): boolean {
  return perms.every((perm) => can(member, perm));
}
