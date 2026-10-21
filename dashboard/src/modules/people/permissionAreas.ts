/**
 * How the roles matrix groups the permissions. The API groups them by code prefix, which leaves
 * sixteen one-row groups ("Audit", "Data", "Branches"…) out of 27; owners think in parts of the
 * business instead, so the matrix uses nine areas that follow the sidebar: access and the company
 * first, then people, HR, pay, work, sales, money, communication and insights. Each area lists its
 * permissions in the order they read best; a permission added later lands in the area of its
 * prefix (or "Other") until it is placed here.
 */
import type { Perm } from "@/core/perms.generated";

export type PermissionAreaId = "access" | "people" | "hr" | "payroll" | "work" | "sales" | "finance" | "comms" | "insights" | "other";

export const PERMISSION_AREAS: ReadonlyArray<{ id: PermissionAreaId; perms: readonly Perm[] }> = [
  { id: "access", perms: ["dashboard.access", "company.settings", "roles.manage", "branches.all", "audit.view", "data.export"] },
  {
    id: "people",
    perms: ["members.view", "members.approve", "members.manage", "positions.manage", "attendance.view", "attendance.manage", "time_off.approve", "time_off.manage"],
  },
  { id: "hr", perms: ["hr.view", "hr.manage", "hr.sensitive", "hr.hiring", "hr.discipline", "hr.suspend", "hr.terminate", "reviews.manage", "assets.manage"] },
  { id: "payroll", perms: ["payroll.view", "payroll.propose", "payroll.manage", "payroll.finalize", "payroll.pay"] },
  {
    id: "work",
    perms: ["tasks.view_all", "tasks.assign", "tasks.templates", "tasks.confirm", "reminders.configure", "projects.view_all", "projects.manage", "projects.time_view"],
  },
  { id: "sales", perms: ["sales.view", "sales.operate", "sales.manage", "sales.invoices", "stock.manage", "crm.view", "crm.manage"] },
  { id: "finance", perms: ["finance.view", "finance.record", "finance.claim", "finance.approve", "finance.manage"] },
  { id: "comms", perms: ["announcements.send", "groups.manage", "knowledge.manage", "agenda.manage"] },
  { id: "insights", perms: ["reports.view", "ai.use", "ai.configure"] },
];

/** Prefix → area, for permissions not listed above yet. */
const BY_PREFIX: Record<string, PermissionAreaId> = {
  dashboard: "access",
  company: "access",
  roles: "access",
  branches: "access",
  audit: "access",
  data: "access",
  members: "people",
  positions: "people",
  attendance: "people",
  time_off: "people",
  hr: "hr",
  reviews: "hr",
  assets: "hr",
  payroll: "payroll",
  tasks: "work",
  reminders: "work",
  projects: "work",
  sales: "sales",
  stock: "sales",
  crm: "sales",
  finance: "finance",
  announcements: "comms",
  groups: "comms",
  knowledge: "comms",
  agenda: "comms",
  reports: "insights",
  ai: "insights",
};

const PLACE = new Map<string, { area: PermissionAreaId; index: number }>();
PERMISSION_AREAS.forEach((area) => area.perms.forEach((code, index) => PLACE.set(code, { area: area.id, index })));
const AREA_ORDER: PermissionAreaId[] = [...PERMISSION_AREAS.map((area) => area.id), "other"];

export function permissionArea(code: string): PermissionAreaId {
  return PLACE.get(code)?.area ?? BY_PREFIX[code.split(".")[0] ?? ""] ?? "other";
}

/**
 * The permissions in areas, areas in sidebar order and permissions in each area's own order (ones
 * not placed yet keep the API's order, after the placed ones). Empty areas are left out.
 */
export function groupByArea<T extends { code: string }>(perms: readonly T[]): Array<{ area: PermissionAreaId; items: T[] }> {
  const buckets = new Map<PermissionAreaId, Array<{ perm: T; rank: number }>>();
  perms.forEach((perm, position) => {
    const area = permissionArea(perm.code);
    const place = PLACE.get(perm.code);
    const rank = place ? place.index : 1000 + position;
    const bucket = buckets.get(area) ?? [];
    bucket.push({ perm, rank });
    buckets.set(area, bucket);
  });
  return AREA_ORDER.filter((area) => buckets.has(area)).map((area) => ({
    area,
    items: buckets
      .get(area)!
      .sort((a, b) => a.rank - b.rank)
      .map((entry) => entry.perm),
  }));
}
