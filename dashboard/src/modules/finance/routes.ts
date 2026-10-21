/**
 * Routes of the finance module, children of /c/:companyId (plan §6.1: `finance`,
 * `finance/accounts[/:id]`, `finance/transactions`, `finance/debts`, `finance/counterparties[/:id]`,
 * `finance/reports/:report`, plus `finance/settings/:tab?` for categories, rates, the period lock
 * and preferences). Pages load lazily.
 */
import type { RouteRecordRaw } from "vue-router";

export const REPORTS = ["pnl", "cash-flow", "balances", "debts-aging", "category-trend"] as const;
export type ReportId = (typeof REPORTS)[number];

export const SETTINGS_TABS = ["categories", "rates", "period", "preferences"] as const;
export type SettingsTab = (typeof SETTINGS_TABS)[number];

export const routes: RouteRecordRaw[] = [
  {
    path: "finance",
    name: "finance.overview",
    component: () => import("./pages/FinanceOverviewPage.vue"),
    meta: { title: "finance.nav.overview", perm: "finance.view" },
  },
  {
    path: "finance/accounts",
    name: "finance.accounts",
    component: () => import("./pages/AccountsPage.vue"),
    meta: { title: "finance.nav.accounts", perm: ["finance.view", "finance.record"] },
  },
  {
    path: "finance/accounts/:accountId(\\d+)",
    name: "finance.account",
    component: () => import("./pages/AccountDetailPage.vue"),
    meta: { title: "finance.accounts.statement", perm: ["finance.view", "finance.record"] },
  },
  {
    path: "finance/transactions",
    name: "finance.transactions",
    component: () => import("./pages/TransactionsPage.vue"),
    meta: { title: "finance.nav.transactions", perm: ["finance.view", "finance.record"] },
  },
  {
    path: "finance/debts",
    name: "finance.debts",
    component: () => import("./pages/DebtsPage.vue"),
    meta: { title: "finance.nav.debts", perm: "finance.view" },
  },
  {
    path: "finance/counterparties",
    name: "finance.counterparties",
    component: () => import("./pages/CounterpartiesPage.vue"),
    meta: { title: "finance.nav.counterparties", perm: "finance.view" },
  },
  {
    path: "finance/counterparties/:partyId(\\d+)",
    name: "finance.counterparty",
    component: () => import("./pages/CounterpartyDetailPage.vue"),
    meta: { title: "finance.parties.detail", perm: "finance.view" },
  },
  {
    path: "finance/reports",
    name: "finance.reports.index",
    redirect: (to) => ({ path: `${to.path.replace(/\/$/, "")}/pnl`, query: to.query }),
    meta: { title: "finance.nav.reports", perm: "finance.view" },
  },
  {
    path: "finance/reports/:report(pnl|cash-flow|balances|debts-aging|category-trend)",
    name: "finance.reports",
    component: () => import("./pages/ReportsPage.vue"),
    meta: { title: "finance.nav.reports", perm: "finance.view" },
  },
  {
    path: "finance/settings/:tab(categories|rates|period|preferences)?",
    name: "finance.settings",
    component: () => import("./pages/FinanceSettingsPage.vue"),
    meta: { title: "finance.nav.settings", perm: "finance.manage" },
  },
];
