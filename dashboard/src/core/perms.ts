/**
 * Permission checks. The codenames themselves live in perms.generated.ts, generated from
 * `apps/members/permissions.py` (plan §5, §13) by `make perms-ts`; everything else imports them
 * from here.
 */
import { PERMS, type Perm } from "@/core/perms.generated";

export { PERMS, type Perm };

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

/** What `hasPerm` needs to know about the caller in one company (a `me.companies` row). */
export interface PermSubject {
  permissions: readonly string[];
  is_owner: boolean;
}

/**
 * True when the subject holds the permission, or any of the listed ones. Owners hold everything
 * (the backend's `is_owner` rule). No requirement means "anyone with dashboard access".
 */
export function hasPerm(subject: PermSubject | null | undefined, required?: PermRequirement): boolean {
  if (!subject) return false;
  if (required === undefined) return true;
  if (subject.is_owner) return true;
  const list: readonly Perm[] = typeof required === "string" ? [required] : required;
  if (list.length === 0) return true;
  return list.some((perm) => subject.permissions.includes(perm));
}
