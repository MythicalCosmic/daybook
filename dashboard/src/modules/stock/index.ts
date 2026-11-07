/**
 * Stock and medicines (Dorilar va ombor): the catalogue with its prescription, controlled and
 * cold-chain marks and the spreadsheet import; stock by pharmacy with its batches (series and
 * expiry); the expiry board; goods receipts (Kirim, nakladnoy) that open a payable; transfers
 * between pharmacies; write-offs and their destruction acts; counts; recalls; distributors; the
 * controlled-substance register and the prescription log; and Settings › Stock. Behind the
 * "stock" switch. Pages load on first use (lazy.ts).
 */
import { ClipboardList, FileUp, Hourglass, PackagePlus, Pill, ShieldAlert } from "@lucide/vue";
import { defineAsyncComponent } from "vue";

import { defineModule } from "@/core/modules";
import { counter } from "@/core/pulse";

import { lazy, routes } from "./routes";

const READ = ["sales.view", "stock.manage", "stock.operate"] as const;

export default defineModule({
  id: "stock",
  group: "money",
  order: 5,
  icon: Pill,
  title: "stock.title",
  perm: READ,
  feature: "stock",
  routes,
  nav: [
    { key: "products", title: "stock.nav.products", to: "stock/products" },
    { key: "levels", title: "stock.nav.levels", to: "stock/levels", badge: counter("inventory.low") },
    { key: "expiry", title: "stock.nav.expiry", to: "stock/expiry", badge: counter("inventory.expiring") },
    { key: "receipts", title: "stock.nav.receipts", to: "stock/receipts", badge: counter("inventory.to_post") },
    { key: "transfers", title: "stock.nav.transfers", to: "stock/transfers" },
    { key: "writeoffs", title: "stock.nav.writeoffs", to: "stock/write-offs" },
    { key: "counts", title: "stock.nav.counts", to: "stock/counts" },
    { key: "recalls", title: "stock.nav.recalls", to: "stock/recalls" },
    { key: "suppliers", title: "stock.nav.suppliers", to: "stock/suppliers" },
    { key: "journals", title: "stock.nav.journals", to: "stock/journals", perm: "stock.controlled" },
  ],
  badge: counter("inventory.to_post"),
  // Every `inventory.*` pulse key (and the bare `inventory` version) refreshes the module.
  invalidates: ["inventory"],
  commands: (ctx) => [
    {
      id: "stock.receipt",
      title: ctx.t("stock.cmd.receipt"),
      icon: PackagePlus,
      keywords: ["kirim", "nakladnoy", "приход", "накладная", "receipt", "delivery"],
      perm: ["stock.manage", "stock.operate"],
      run: () => ctx.go("stock/receipts?new=1"),
    },
    {
      id: "stock.import",
      title: ctx.t("stock.cmd.import"),
      icon: FileUp,
      keywords: ["import", "excel", "xlsx", "dorilar", "препараты", "katalog", "каталог"],
      perm: "stock.manage",
      run: () => ctx.go("stock/products?import=1"),
    },
    {
      id: "stock.expiry",
      title: ctx.t("stock.cmd.expiry"),
      icon: Hourglass,
      keywords: ["yaroqlilik", "muddati", "срок годности", "expiry", "просрочка"],
      perm: READ,
      run: () => ctx.go("stock/expiry"),
    },
    {
      id: "stock.count",
      title: ctx.t("stock.cmd.count"),
      icon: ClipboardList,
      keywords: ["inventarizatsiya", "инвентаризация", "count", "sanash"],
      perm: ["stock.manage", "stock.operate"],
      run: () => ctx.go("stock/counts?new=1"),
    },
    {
      id: "stock.recall",
      title: ctx.t("stock.cmd.recall"),
      icon: ShieldAlert,
      keywords: ["recall", "seriya", "серия", "отзыв", "brak", "брак"],
      perm: "stock.manage",
      run: () => ctx.go("stock/recalls?new=1"),
    },
  ],
  settings: [
    {
      id: "stock",
      title: "stock.settings.title",
      perm: "stock.manage",
      feature: "stock",
      order: 46,
      icon: Pill,
      component: defineAsyncComponent(() => lazy().then((m) => m.panels.settings())),
    },
  ],
  // `startapp=receipt_<id>` opens a receipt, `transfer_<id>` a transfer, `stock` the catalogue.
  deepLinks: {
    stock: () => "stock/products",
    receipt: (id) => (/^\d+$/.test(id) ? `stock/receipts/${id}` : "stock/receipts"),
    transfer: (id) => (/^\d+$/.test(id) ? `stock/transfers?transfer=${id}` : "stock/transfers"),
  },
  messages: (language) => import(`./i18n/${language}.json`),
});
