/**
 * Fixed assets and depreciation (Asosiy vositalar va amortizatsiya): the register of what the
 * company owns with its value today, each asset's page (its depreciation month by month, the tax
 * book, who holds it, its upkeep and timeline), the depreciation report and the roll-forward,
 * planning (replacements, repairs that approach a new one's price, idle money, upkeep coming up)
 * and inventory counts. Behind the "assets" switch. Pages load on first use (lazy.ts).
 */
import { Boxes, ClipboardCheck, PackagePlus, TrendingDown } from "@lucide/vue";
import { defineAsyncComponent } from "vue";

import { defineModule } from "@/core/modules";

import { lazy, routes } from "./routes";

const READ = ["assets.manage", "finance.view"] as const;

export default defineModule({
  id: "assets",
  group: "money",
  order: 35,
  icon: Boxes,
  title: "assets.title",
  perm: READ,
  feature: "assets",
  routes,
  nav: [
    { key: "items", title: "assets.nav.items", to: "assets/items" },
    { key: "depreciation", title: "assets.nav.depreciation", to: "assets/depreciation" },
    { key: "planning", title: "assets.nav.planning", to: "assets/planning" },
    { key: "permits", title: "assets.nav.permits", to: "assets/permits" },
    { key: "counts", title: "assets.nav.counts", to: "assets/counts" },
  ],
  invalidates: ["assets"],
  commands: (ctx) => [
    {
      id: "assets.new",
      title: ctx.t("assets.cmd.new"),
      icon: PackagePlus,
      keywords: ["asset", "asosiy vosita", "основное средство", "jihoz", "оборудование", "equipment", "muzlatgich"],
      perm: "assets.manage",
      run: () => ctx.go("assets/items?new=1"),
    },
    {
      id: "assets.depreciation",
      title: ctx.t("assets.cmd.depreciation"),
      icon: TrendingDown,
      keywords: ["amortizatsiya", "амортизация", "depreciation", "eskirish", "износ"],
      perm: READ,
      run: () => ctx.go("assets/depreciation"),
    },
    {
      id: "assets.count",
      title: ctx.t("assets.cmd.count"),
      icon: ClipboardCheck,
      keywords: ["inventarizatsiya", "инвентаризация", "count", "sanash"],
      perm: "assets.manage",
      run: () => ctx.go("assets/counts?new=1"),
    },
  ],
  settings: [
    {
      id: "assets",
      title: "assets.settings.title",
      perm: "assets.manage",
      feature: "assets",
      order: 47,
      icon: Boxes,
      component: defineAsyncComponent(() => lazy().then((m) => m.panels.settings())),
    },
  ],
  // `startapp=asset_<id>` opens an asset (QR labels), `assets` the register.
  deepLinks: {
    assets: () => "assets/items",
    asset: (id) => (/^\d+$/.test(id) ? `assets/items/${id}` : "assets/items"),
  },
  messages: (language) => import(`./i18n/${language}.json`),
});
