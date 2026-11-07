/** Routes of stock, children of /c/:companyId. Pages load lazily through lazy.ts. */
import type { RouteRecordRaw } from "vue-router";

export const lazy = () => import("./lazy");

const READ = ["sales.view", "stock.manage", "stock.operate"] as const;

export const routes: RouteRecordRaw[] = [
  { path: "stock", redirect: (to) => ({ path: `/c/${String(to.params.companyId)}/stock/products` }) },
  {
    path: "stock/products",
    name: "stock.products",
    component: () => lazy().then((m) => m.pages.products()),
    meta: { title: "stock.nav.products", perm: READ },
  },
  {
    path: "stock/levels",
    name: "stock.levels",
    component: () => lazy().then((m) => m.pages.levels()),
    meta: { title: "stock.nav.levels", perm: READ },
  },
  {
    path: "stock/expiry",
    name: "stock.expiry",
    component: () => lazy().then((m) => m.pages.expiry()),
    meta: { title: "stock.nav.expiry", perm: READ },
  },
  {
    path: "stock/receipts",
    name: "stock.receipts",
    component: () => lazy().then((m) => m.pages.receipts()),
    meta: { title: "stock.nav.receipts", perm: READ },
  },
  {
    path: "stock/receipts/:receiptId(\\d+)",
    name: "stock.receipt",
    component: () => lazy().then((m) => m.pages.receipt()),
    meta: { title: "stock.receipt.title", perm: READ },
  },
  {
    path: "stock/transfers",
    name: "stock.transfers",
    component: () => lazy().then((m) => m.pages.transfers()),
    meta: { title: "stock.nav.transfers", perm: READ },
  },
  // Notifications and Needs you link to a transfer or a recall by its path: their pages open them
  // in a side panel.
  {
    path: "stock/transfers/:transferId(\\d+)",
    redirect: (to) => ({ path: `/c/${String(to.params.companyId)}/stock/transfers`, query: { transfer: String(to.params.transferId) } }),
  },
  {
    path: "stock/recalls/:recallId(\\d+)",
    redirect: (to) => ({ path: `/c/${String(to.params.companyId)}/stock/recalls`, query: { recall: String(to.params.recallId), status: "all" } }),
  },
  {
    path: "stock/write-offs",
    name: "stock.writeoffs",
    component: () => lazy().then((m) => m.pages.writeoffs()),
    meta: { title: "stock.nav.writeoffs", perm: READ },
  },
  {
    path: "stock/write-offs/:writeoffId(\\d+)",
    name: "stock.writeoff",
    component: () => lazy().then((m) => m.pages.writeoff()),
    meta: { title: "stock.writeoff.title", perm: READ },
  },
  {
    path: "stock/counts",
    name: "stock.counts",
    component: () => lazy().then((m) => m.pages.counts()),
    meta: { title: "stock.nav.counts", perm: READ },
  },
  {
    path: "stock/counts/:countId(\\d+)",
    name: "stock.count",
    component: () => lazy().then((m) => m.pages.count()),
    meta: { title: "stock.count.title", perm: READ },
  },
  {
    path: "stock/recalls",
    name: "stock.recalls",
    component: () => lazy().then((m) => m.pages.recalls()),
    meta: { title: "stock.nav.recalls", perm: READ },
  },
  {
    path: "stock/defektura",
    name: "stock.defektura",
    component: () => lazy().then((m) => m.pages.defektura()),
    meta: { title: "stock.nav.defektura", perm: READ },
  },
  {
    path: "stock/suppliers",
    name: "stock.suppliers",
    component: () => lazy().then((m) => m.pages.suppliers()),
    meta: { title: "stock.nav.suppliers", perm: READ },
  },
  {
    path: "stock/journals",
    name: "stock.journals",
    component: () => lazy().then((m) => m.pages.journals()),
    meta: { title: "stock.nav.journals", perm: "stock.controlled" },
  },
];
