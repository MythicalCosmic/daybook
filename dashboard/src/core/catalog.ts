/**
 * The console's information architecture: which module sits in which sidebar group, in what order,
 * behind which permission and switch, and what its pages are called (plan §6.1 and §13).
 *
 * Module engineers copy their entry into `defineModule` (id, group, order, perm, feature, hotkey,
 * routes and nav paths). registry.test.ts fails when a real module's group or order drifts from
 * here, so the sidebar stays in the order the plan designed. Paths are relative to /c/:companyId.
 * The dev mock (src/dev/stubModules.ts) builds placeholder modules from this table so the whole
 * shell can be seen before the packages land.
 *
 * Packages (§11, §13.7): W0 lead, A identity and setup, B tasks, C people and announcements,
 * D/I finance, E/J sales and stock, F attendance, G HR and hiring, H payroll, K AI, L leave,
 * N overview, insights, audit, exports, R recognition, T projects, Q knowledge and calendar,
 * S people lifecycle, U CRM.
 */
import type { CompanyFeature } from "@/core/features";
import type { ModuleGroup } from "@/core/modules";
import type { PermRequirement } from "@/core/perms";

export interface CatalogPage {
  id: string;
  to: string;
  perm?: PermRequirement;
  feature?: CompanyFeature;
  /** Pulse counter shown as the item's badge. */
  badge?: string;
}

export interface CatalogEntry {
  id: string;
  group: ModuleGroup;
  order: number;
  /** Work package that owns the module. */
  pkg: string;
  perm?: PermRequirement;
  feature?: CompanyFeature;
  hotkey?: string;
  /** Pulse counter shown on the module's sidebar row. */
  badge?: string;
  pages: CatalogPage[];
}

export const CATALOG: readonly CatalogEntry[] = [
  // Overview
  { id: "overview", group: "overview", order: 10, pkg: "W0 → N", hotkey: "o", pages: [{ id: "today", to: "" }] },
  { id: "inbox", group: "overview", order: 20, pkg: "W0", hotkey: "i", badge: "queue.total", pages: [{ id: "inbox", to: "inbox" }] },

  // Work
  {
    id: "tasks",
    group: "work",
    order: 10,
    pkg: "B",
    hotkey: "t",
    pages: [
      { id: "all", to: "tasks" },
      { id: "reviews", to: "tasks/reviews", badge: "tasks.review" },
      { id: "photos", to: "tasks/photos" },
    ],
  },
  {
    id: "projects",
    group: "work",
    order: 20,
    pkg: "T",
    hotkey: "j",
    pages: [
      { id: "all", to: "projects" },
      { id: "roadmap", to: "projects/roadmap" },
    ],
  },
  { id: "routines", group: "work", order: 30, pkg: "B", perm: "tasks.templates", hotkey: "r", pages: [{ id: "all", to: "routines" }] },
  { id: "reminders", group: "work", order: 40, pkg: "B", perm: "reminders.configure", pages: [{ id: "policies", to: "reminders" }] },

  // People
  {
    id: "people",
    group: "people",
    order: 10,
    pkg: "C",
    perm: "members.view",
    hotkey: "p",
    pages: [
      { id: "team", to: "people" },
      { id: "requests", to: "people/requests", perm: "members.approve", badge: "members.pending" },
      { id: "roles", to: "people/roles", perm: "roles.manage" },
      { id: "positions", to: "people/positions", perm: "positions.manage" },
    ],
  },
  {
    id: "attendance",
    group: "people",
    order: 20,
    pkg: "F",
    perm: "attendance.view",
    feature: "attendance",
    hotkey: "a",
    badge: "attendance.not_in",
    pages: [
      { id: "today", to: "attendance" },
      { id: "timesheet", to: "attendance/timesheet" },
      { id: "roster", to: "attendance/roster" },
      { id: "schedules", to: "attendance/schedules", perm: "attendance.manage" },
      { id: "swaps", to: "attendance/swaps", perm: "attendance.manage", badge: "attendance.swaps" },
      { id: "corrections", to: "attendance/corrections", perm: "attendance.manage", badge: "attendance.corrections" },
    ],
  },
  {
    id: "timeoff",
    group: "people",
    order: 30,
    pkg: "C + L",
    perm: ["time_off.approve", "time_off.manage"],
    badge: "timeoff.pending",
    pages: [
      { id: "calendar", to: "time-off" },
      { id: "holidays", to: "time-off/holidays" },
      { id: "balances", to: "time-off/balances", perm: "time_off.manage" },
      { id: "types", to: "time-off/types", perm: "time_off.manage" },
    ],
  },
  {
    id: "hr",
    group: "people",
    order: 40,
    pkg: "G",
    perm: ["hr.view", "hr.hiring"],
    feature: "hr",
    hotkey: "h",
    badge: "hr.expiring",
    pages: [
      { id: "documents", to: "hr/documents", perm: "hr.view" },
      { id: "contracts", to: "hr/contracts", perm: "hr.view" },
      { id: "templates", to: "hr/contract-templates", perm: "hr.manage" },
      { id: "policies", to: "hr/policies", perm: "hr.view" },
      { id: "celebrations", to: "hr/celebrations", perm: "hr.view" },
      { id: "hiring", to: "hr/hiring", perm: "hr.hiring" },
    ],
  },
  {
    id: "lifecycle",
    group: "people",
    order: 50,
    pkg: "S",
    perm: ["hr.view", "hr.discipline", "hr.suspend", "hr.terminate", "assets.manage", "reviews.manage"],
    feature: "hr",
    pages: [
      { id: "org", to: "lifecycle/org", perm: "hr.view" },
      { id: "discipline", to: "lifecycle/discipline", perm: ["hr.discipline", "hr.view"] },
      { id: "suspensions", to: "lifecycle/suspensions", perm: ["hr.suspend", "hr.view"] },
      { id: "terminations", to: "lifecycle/terminations", perm: ["hr.terminate", "hr.view"], badge: "lifecycle.resignations" },
      { id: "changes", to: "lifecycle/job-changes", perm: ["hr.manage", "hr.view"], badge: "lifecycle.job_changes" },
      { id: "equipment", to: "lifecycle/equipment", perm: ["assets.manage", "hr.manage"] },
      { id: "reviews", to: "lifecycle/reviews", perm: "reviews.manage" },
    ],
  },
  { id: "recognition", group: "people", order: 60, pkg: "R", feature: "recognition", pages: [{ id: "kudos", to: "recognition" }] },

  // Money
  {
    id: "sales",
    group: "money",
    order: 10,
    pkg: "E + J",
    perm: ["sales.view", "sales.invoices"],
    feature: "sales",
    hotkey: "s",
    pages: [
      { id: "overview", to: "sales", perm: "sales.view" },
      { id: "shifts", to: "sales/shifts", perm: "sales.view", badge: "sales.to_verify" },
      { id: "cash", to: "sales/cash", perm: "sales.view" },
      { id: "entries", to: "sales/entries", perm: "sales.view" },
      { id: "targets", to: "sales/targets", perm: "sales.view" },
      { id: "invoices", to: "sales/invoices", perm: ["sales.invoices", "finance.view"], badge: "sales.invoices_overdue" },
      { id: "customers", to: "sales/customers", perm: "sales.view" },
    ],
  },
  {
    id: "stock",
    group: "money",
    order: 20,
    pkg: "J",
    perm: ["sales.view", "stock.manage"],
    feature: "stock",
    pages: [
      { id: "products", to: "stock/products" },
      { id: "levels", to: "stock/levels", badge: "stock.low" },
      { id: "receipts", to: "stock/receipts", perm: "stock.manage" },
      { id: "counts", to: "stock/counts", perm: "stock.manage" },
    ],
  },
  {
    id: "finance",
    group: "money",
    order: 30,
    pkg: "D + I",
    perm: ["finance.view", "finance.record", "finance.approve"],
    feature: "finance",
    hotkey: "f",
    pages: [
      { id: "overview", to: "finance", perm: "finance.view" },
      { id: "accounts", to: "finance/accounts", perm: "finance.view" },
      { id: "transactions", to: "finance/transactions" },
      { id: "debts", to: "finance/debts", perm: "finance.view", badge: "finance.overdue" },
      { id: "counterparties", to: "finance/counterparties", perm: "finance.view" },
      { id: "reports", to: "finance/reports/pnl", perm: "finance.view" },
      { id: "budgets", to: "finance/budgets", perm: "finance.view" },
      { id: "recurring", to: "finance/recurring", perm: "finance.view" },
      { id: "calendar", to: "finance/calendar", perm: "finance.view" },
      { id: "claims", to: "finance/claims", perm: "finance.approve", badge: "finance.claims" },
    ],
  },
  {
    id: "payroll",
    group: "money",
    order: 40,
    pkg: "H",
    perm: ["payroll.view", "payroll.propose", "payroll.manage"],
    feature: "payroll",
    hotkey: "y",
    pages: [
      { id: "runs", to: "payroll", perm: "payroll.view" },
      { id: "pay", to: "payroll/pay", perm: "payroll.view" },
      { id: "adjustments", to: "payroll/adjustments", badge: "payroll.pending" },
      { id: "rules", to: "payroll/rules", perm: "payroll.manage" },
      { id: "advances", to: "payroll/advances", perm: ["payroll.manage", "payroll.pay"] },
    ],
  },
  { id: "crm", group: "money", order: 50, pkg: "U", perm: ["crm.view", "crm.manage"], pages: [{ id: "deals", to: "crm" }] },

  // Communication
  {
    id: "comms",
    group: "comms",
    order: 10,
    pkg: "C",
    perm: "announcements.send",
    hotkey: "m",
    pages: [{ id: "announcements", to: "announcements" }],
  },
  { id: "groups", group: "comms", order: 20, pkg: "A", perm: "groups.manage", pages: [{ id: "groups", to: "groups" }] },
  { id: "agenda", group: "comms", order: 30, pkg: "Q", hotkey: "c", pages: [{ id: "calendar", to: "calendar" }] },
  { id: "knowledge", group: "comms", order: 40, pkg: "Q", hotkey: "k", pages: [{ id: "spaces", to: "knowledge" }] },

  // Insights
  {
    id: "reports",
    group: "insights",
    order: 10,
    pkg: "B",
    perm: "reports.view",
    pages: [
      { id: "team", to: "reports/team" },
      { id: "routines", to: "reports/routines" },
    ],
  },
  {
    id: "insights",
    group: "insights",
    order: 20,
    pkg: "N",
    perm: "reports.view",
    badge: "insights.open",
    pages: [
      { id: "insights", to: "insights" },
      { id: "briefings", to: "briefings" },
    ],
  },
  { id: "ai", group: "insights", order: 30, pkg: "K", perm: "ai.use", feature: "ai", pages: [{ id: "assistant", to: "ai" }] },

  // Company
  { id: "settings", group: "company", order: 10, pkg: "A", hotkey: ",", pages: [{ id: "panels", to: "settings" }] },
  { id: "exports", group: "company", order: 20, pkg: "W0 → N", perm: "data.export", pages: [{ id: "list", to: "exports" }] },
  { id: "audit", group: "company", order: 30, pkg: "N", perm: "audit.view", pages: [{ id: "log", to: "audit" }] },
];

/**
 * Modules with no sidebar row: `auth` brings only public routes (A); `setup` is "Get started",
 * reached from the progress pill in the `shell.nav.top` slot (A).
 */
export const CATALOG_HEADLESS: readonly string[] = ["auth", "setup"];

export function catalogEntry(id: string): CatalogEntry | undefined {
  return CATALOG.find((entry) => entry.id === id);
}
