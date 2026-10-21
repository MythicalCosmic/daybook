/**
 * How a routine's History tab reads its audit rows: the audit log stores the template's raw
 * values (branch, people, positions and policy as ids, days as numbers, proof as a code), so
 * they are turned back into names and words here, with `#id` for anything no longer listed.
 */
import type { PlanOptions } from "./types";

type Translate = (key: string) => string;

export interface RoutineAuditLookups {
  options: PlanOptions | undefined;
  branches: Array<{ id: number; name: string }>;
}

export function routineFieldLabels(t: Translate): Record<string, string> {
  return {
    title: t("routines.field.title"),
    description: t("routines.field.description"),
    weekdays: t("routines.field.weekdays"),
    due_time: t("routines.field.dueTime"),
    due_after_days: t("routines.field.dueAfter"),
    starts_on: t("routines.field.startsOn"),
    positions: t("routines.field.positions"),
    assignees: t("routines.field.people"),
    branch: t("routines.field.branch"),
    proof: t("routines.field.proof"),
    needs_confirmation: t("routines.field.needsConfirmation"),
    checklist: t("routines.field.checklist"),
    reminder_policy: t("routines.field.policy"),
    escalate_to: t("routines.field.escalateTo"),
    is_active: t("routines.field.active"),
  };
}

function named(list: Array<{ id: number; name: string }> | undefined, id: unknown): string {
  return list?.find((item) => item.id === id)?.name ?? `#${String(id)}`;
}

export function formatRoutineAudit(t: Translate, lookups: RoutineAuditLookups) {
  return (field: string, value: unknown): string | null => {
    if (value === null || value === undefined || value === "") return null;
    const ids = Array.isArray(value) ? value : [value];
    switch (field) {
      case "branch":
        return named(lookups.branches, value);
      case "escalate_to":
        return named(lookups.options?.people, value);
      case "reminder_policy":
        return named(lookups.options?.policies, value);
      case "assignees":
        return ids.length ? ids.map((id) => named(lookups.options?.people, id)).join(", ") : null;
      case "positions":
        return ids.length ? ids.map((id) => named(lookups.options?.positions, id)).join(", ") : null;
      case "weekdays":
        return ids.length ? ids.map((day) => t(`routines.day.${String(day)}`)).join(", ") : null;
      case "proof":
        return t(`routines.proof.${String(value)}`);
      case "due_time":
        return String(value).slice(0, 5);
      default:
        return null;
    }
  };
}
