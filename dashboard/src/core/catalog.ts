/**
 * The console's information architecture: which module sits in which sidebar group, in what order,
 * behind which permission and switch, and what its pages are called (plan §6.1 and §13).
 *
 * Module engineers copy their entry into `defineModule` (id, group, order, perm, feature, hotkey,
 * routes and nav paths). registry.test.ts fails when a real module's group or order drifts from
 * here, so the sidebar stays in the order the plan designed. Paths are relative to /c/:companyId.
 * The dev mock (src/dev/stubModules.ts) builds placeholder modules from this table so the whole
 * shell can be seen before the packages land.
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
  /** Work package that owns the module (§11, §13.6). */
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
  { id: "overview", group: "overview", order: 10, pkg: "A", hotkey: "o", pages: [{ id: "today", to: "" }] },
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
    pkg: "M",
    hotkey: "j",
    pages: [
      { id: "all", to: "projects" },
      { id: "roadmap", to: "projects/roadmap" },
      { id: "time", to: "projects/time" },
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
    id: "lifecycle",
    group: "people",
    order: 20,
    pkg: "N1",
    perm: ["hr.view", "hr.discipline", "hr.suspend", "hr.terminate", "org.manage"],
    feature: "hr",
    pages: [
      { id: "org", to: "org" },
      { id: "discipline", to: "lifecycle/discipline", perm: ["hr.discipline", "hr.view"] },
      { id: "suspensions", to: "lifecycle/suspensions", perm: ["hr.suspend", "hr.view"] },
      { id: "terminations", to: "lifecycle/terminations", perm: ["hr.terminate", "hr.view"], badge: "lifecycle.requested" },
      { id: "changes", to: "lifecycle/changes", perm: ["hr.manage", "org.manage"] },
    ],
  },
  {
    id: "attendance",
    group: "people",
    order: 30,
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
      { id: "corrections", to: "attendance/corrections", perm: "attendance.manage", badge: "attendance.corrections" },
    ],
  },
  {
    id: "timeoff",
    group: "people",
    order: 40,
    pkg: "C+G",
    perm: ["time_off.approve", "time_off.manage"],
    badge: "timeoff.pending",
    pages: [
      { id: "calendar", to: "time-off" },
      { id: "balances", to: "time-off/balances", perm: "time_off.manage" },
      { id: "types", to: "time-off/types", perm: "time_off.manage" },
      { id: "holidays", to: "time-off/holidays" },
    ],
  },
  {
    id: "hr",
    group: "people",
    order: 50,
    pkg: "G",
    perm: "hr.view",
    feature: "hr",
    hotkey: "h",
    badge: "hr.expiring",
    pages: [
      { id: "documents", to: "hr/documents" },
      { id: "contracts", to: "hr/contracts" },
      { id: "policies", to: "hr/policies" },
      { id: "celebrations", to: "hr/celebrations" },
    ],
  },
  {
    id: "hiring",
    group: "people",
    order: 60,
    pkg: "N2",
    perm: "hiring.manage",
    feature: "hr",
    pages: [
      { id: "vacancies", to: "hiring" },
      { id: "onboarding", to: "hiring/onboarding" },
    ],
  },
  { id: "assets", group: "people", order: 70, pkg: "N2", perm: "assets.manage", feature: "hr", pages: [{ id: "all", to: "assets" }] },
  {
    id: "reviews",
    group: "people",
    order: 80,
    pkg: "N2",
    perm: "reviews.manage",
    feature: "hr",
    pages: [
      { id: "cycles", to: "reviews" },
      { id: "goals", to: "reviews/goals" },
      { id: "kudos", to: "reviews/kudos" },
    ],
  },

  // Money
  {
    id: "sales",
    group: "money",
    order: 10,
    pkg: "E+J",
    perm: "sales.view",
    feature: "sales",
    hotkey: "s",
    pages: [
      { id: "overview", to: "sales" },
      { id: "shifts", to: "sales/shifts", badge: "sales.to_verify" },
      { id: "cash", to: "sales/cash" },
      { id: "entries", to: "sales/entries" },
      { id: "targets", to: "sales/targets" },
      { id: "customers", to: "sales/customers" },
    ],
  },
  {
    id: "stock",
    group: "money",
    order: 20,
    pkg: "J",
    perm: "stock.manage",
    feature: "stock",
    pages: [
      { id: "products", to: "stock/products" },
      { id: "levels", to: "stock/levels", badge: "stock.low" },
      { id: "receipts", to: "stock/receipts" },
      { id: "counts", to: "stock/counts" },
    ],
  },
  {
    id: "finance",
    group: "money",
    order: 30,
    pkg: "D+I",
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
  {
    id: "crm",
    group: "money",
    order: 50,
    pkg: "R",
    perm: ["crm.view", "crm.manage", "invoices.manage", "finance.view"],
    pages: [
      { id: "deals", to: "crm", perm: ["crm.view", "crm.manage"] },
      { id: "invoices", to: "crm/invoices", perm: ["invoices.manage", "finance.view"] },
    ],
  },

  // Communication
  {
    id: "comms",
    group: "comms",
    order: 10,
    pkg: "C",
    perm: ["announcements.send", "groups.manage"],
    hotkey: "m",
    pages: [
      { id: "announcements", to: "announcements", perm: "announcements.send" },
      { id: "groups", to: "groups", perm: "groups.manage" },
    ],
  },
  { id: "agenda", group: "comms", order: 20, pkg: "Q", hotkey: "c", pages: [{ id: "calendar", to: "calendar" }] },
  { id: "knowledge", group: "comms", order: 30, pkg: "Q", hotkey: "k", pages: [{ id: "spaces", to: "knowledge" }] },

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
    id: "ai",
    group: "insights",
    order: 20,
    pkg: "K",
    perm: ["ai.use", "reports.view"],
    pages: [
      { id: "assistant", to: "ai", perm: "ai.use", feature: "ai" },
      { id: "insights", to: "ai/insights", perm: "reports.view", badge: "insights.open" },
      { id: "briefings", to: "ai/briefings", perm: "reports.view" },
    ],
  },

  // Company
  { id: "settings", group: "company", order: 10, pkg: "A", hotkey: ",", pages: [{ id: "panels", to: "settings" }] },
  { id: "audit", group: "company", order: 20, pkg: "A", perm: "audit.view", pages: [{ id: "log", to: "audit" }] },
];

/** Modules with no sidebar presence: the auth module only brings public routes. */
export const CATALOG_HEADLESS: readonly string[] = ["auth"];

export function catalogEntry(id: string): CatalogEntry | undefined {
  return CATALOG.find((entry) => entry.id === id);
}
