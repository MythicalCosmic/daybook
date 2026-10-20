/**
 * Every permission codename a role can grant, mirroring `apps/members/permissions.py` (plan §5 and §13).
 * The backend's registry is the source of truth; `GET /owner/permissions/` returns the same codes with
 * their labels. A test in src/__tests__/registry.test.ts keeps this list free of duplicates and typos.
 */
export const PERMS = [
  // Existing (M0–M7)
  "members.view",
  "members.approve",
  "members.manage",
  "roles.manage",
  "positions.manage",
  "tasks.view_all",
  "tasks.assign",
  "tasks.templates",
  "tasks.confirm",
  "reminders.configure",
  "groups.manage",
  "reports.view",
  "time_off.approve",
  "announcements.send",

  // Owner console (§5)
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

  // Owner's additions (§13): projects, people lifecycle, knowledge, CRM
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

export type Perm = (typeof PERMS)[number];

/** A requirement on a nav item, route or widget: one permission, or any of several. */
export type PermRequirement = Perm | readonly Perm[];

const known = new Set<string>(PERMS);

export function isPerm(value: string): value is Perm {
  return known.has(value);
}

/** The area a codename belongs to ("finance.view" → "finance"), used to group the roles matrix. */
export function permArea(perm: Perm): string {
  return perm.slice(0, perm.indexOf("."));
}

/** What `hasPerm` needs to know about the caller in one company. */
export interface PermSubject {
  permissions: readonly string[];
  role: { is_owner: boolean };
}

/**
 * True when the subject holds the permission, or any of the listed ones. Owners hold everything
 * (the backend's `is_owner` rule). No requirement means "anyone with dashboard access".
 */
export function hasPerm(subject: PermSubject | null | undefined, required?: PermRequirement): boolean {
  if (!subject) return false;
  if (required === undefined) return true;
  if (subject.role.is_owner) return true;
  const list: readonly Perm[] = typeof required === "string" ? [required] : required;
  if (list.length === 0) return true;
  return list.some((perm) => subject.permissions.includes(perm));
}
