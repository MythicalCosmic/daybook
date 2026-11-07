/**
 * Routes of sales and cash (plan §6.1: `sales`, `sales/shifts`, `sales/cash`, `sales/entries`,
 * `sales/targets`, plus `sales/cashiers`, `sales/setup` and §14.7's `sales/import` and
 * `sales/lines`), children of /c/:companyId. Pages load
 * lazily; the shift drawer lives in the URL (`?shift=1042`) on any of them that opens one.
 */
import type { RouteRecordRaw } from "vue-router";

export const routes: RouteRecordRaw[] = [
  {
    path: "sales",
    name: "sales.overview",
    component: () => import("./pages/SalesOverviewPage.vue"),
    meta: { title: "sales.title", perm: "sales.view" },
  },
  {
    path: "sales/shifts",
    name: "sales.shifts",
    component: () => import("./pages/ShiftsPage.vue"),
    meta: { title: "sales.nav.shifts", perm: "sales.view" },
  },
  {
    path: "sales/shifts/:shiftId(\\d+)",
    name: "sales.shift",
    redirect: (to) => ({ path: `/c/${String(to.params.companyId)}/sales/shifts`, query: { shift: String(to.params.shiftId) } }),
  },
  {
    path: "sales/cash",
    name: "sales.cash",
    component: () => import("./pages/CashPage.vue"),
    meta: { title: "sales.nav.cash", perm: "sales.view" },
  },
  {
    path: "sales/cashiers",
    name: "sales.cashiers",
    component: () => import("./pages/CashiersPage.vue"),
    meta: { title: "sales.nav.cashiers", perm: "sales.view" },
  },
  {
    path: "sales/targets",
    name: "sales.targets",
    component: () => import("./pages/TargetsPage.vue"),
    meta: { title: "sales.nav.targets", perm: "sales.view" },
  },
  {
    path: "sales/entries",
    name: "sales.entries",
    component: () => import("./pages/EntriesPage.vue"),
    meta: { title: "sales.nav.entries", perm: "sales.view" },
  },
  {
    path: "sales/import",
    name: "sales.import",
    component: () => import("./pages/ImportPage.vue"),
    meta: { title: "sales.nav.import", perm: "sales.manage" },
  },
  {
    path: "sales/lines",
    name: "sales.lines",
    component: () => import("./pages/LinesPage.vue"),
    meta: { title: "sales.nav.lines", perm: "sales.view" },
  },
  {
    path: "sales/customers",
    name: "sales.customers",
    component: () => import("./pages/CustomersPage.vue"),
    meta: { title: "sales.nav.customers", perm: "sales.view" },
  },
  {
    path: "sales/invoices",
    name: "sales.invoices",
    component: () => import("./pages/InvoicesPage.vue"),
    meta: { title: "sales.nav.invoices", perm: ["sales.view", "sales.invoices"] },
  },
  {
    path: "sales/setup",
    name: "sales.setup",
    component: () => import("./pages/SetupPage.vue"),
    meta: { title: "sales.nav.setup", perm: "sales.view" },
  },
];
