/**
 * Payroll (package H, plan §1.8, §3.13, §4.11, §6.2): monthly runs and payslips, pay setups,
 * bonuses and fines (by hand and by rules, with a live preview), advances, the payroll settings
 * panel, the Person 360 "Pay" tab and the Overview tile for the next payroll. Kept tiny: pages,
 * the widget, the panel and the tab load on first use (lazy.ts).
 */
import { Banknote, CalendarPlus, Gift, HandCoins, Scale, Settings2, WalletCards } from "@lucide/vue";
import { defineAsyncComponent } from "vue";

import { defineModule } from "@/core/modules";
import { counter } from "@/core/pulse";

import { lazy, routes } from "./routes";

export default defineModule({
  id: "payroll",
  group: "money",
  order: 40,
  icon: Banknote,
  title: "payroll.title",
  perm: ["payroll.view", "payroll.propose", "payroll.manage"],
  feature: "payroll",
  hotkey: "y",
  routes,
  nav: [
    { key: "runs", title: "payroll.nav.runs", to: "payroll", perm: "payroll.view", exact: true },
    { key: "pay", title: "payroll.nav.pay", to: "payroll/pay", perm: "payroll.view" },
    { key: "adjustments", title: "payroll.nav.adjustments", to: "payroll/adjustments", badge: counter("payroll.pending") },
    { key: "rules", title: "payroll.nav.rules", to: "payroll/rules", perm: "payroll.manage" },
    { key: "advances", title: "payroll.nav.advances", to: "payroll/advances", perm: ["payroll.manage", "payroll.pay"] },
  ],
  // Proposed bonuses and fines, open disputes and advance requests waiting for a decision.
  badge: counter("payroll.pending"),
  invalidates: ["payroll"],
  commands: (ctx) => [
    {
      id: "payroll.prepare",
      title: ctx.t("payroll.cmd.prepare"),
      icon: CalendarPlus,
      keywords: ["oylik", "ish haqi", "зарплата", "ведомость", "salary", "payroll"],
      perm: "payroll.manage",
      run: () => ctx.go("payroll?prepare=1"),
    },
    {
      id: "payroll.bonus",
      title: ctx.t("payroll.cmd.bonus"),
      icon: Gift,
      keywords: ["bonus", "mukofot", "премия"],
      perm: ["payroll.propose", "payroll.manage"],
      run: () => ctx.go("payroll/adjustments?new=bonus"),
    },
    {
      id: "payroll.fine",
      title: ctx.t("payroll.cmd.fine"),
      icon: Scale,
      keywords: ["jarima", "штраф", "penalty"],
      perm: ["payroll.propose", "payroll.manage"],
      run: () => ctx.go("payroll/adjustments?new=fine"),
    },
    {
      id: "payroll.advance",
      title: ctx.t("payroll.cmd.advance"),
      icon: HandCoins,
      keywords: ["avans", "аванс", "advance", "qarz"],
      perm: "payroll.manage",
      run: () => ctx.go("payroll/advances?new=1"),
    },
    {
      id: "payroll.pay",
      title: ctx.t("payroll.cmd.pay"),
      icon: WalletCards,
      keywords: ["maosh", "оклад", "salary", "rate"],
      perm: "payroll.view",
      run: () => ctx.go("payroll/pay"),
    },
    {
      id: "payroll.settings",
      title: ctx.t("payroll.cmd.settings"),
      icon: Settings2,
      keywords: ["pay day", "maosh kuni", "день зарплаты", "night", "tun"],
      perm: "payroll.manage",
      run: () => ctx.go("settings/payroll"),
    },
  ],
  widgets: [
    {
      id: "payroll.kpi.next",
      span: 1,
      order: 33,
      kind: "kpi",
      perm: "payroll.view",
      feature: "payroll",
      component: defineAsyncComponent(() => lazy().then((m) => m.widgets.next())),
    },
  ],
  settings: [
    {
      id: "payroll",
      title: "payroll.settings.title",
      perm: "payroll.manage",
      feature: "payroll",
      order: 45,
      icon: Banknote,
      component: defineAsyncComponent(() => lazy().then((m) => m.panels.settings())),
    },
  ],
  personTabs: [
    {
      id: "pay",
      title: "payroll.personTab",
      perm: "payroll.view",
      feature: "payroll",
      order: 40,
      component: defineAsyncComponent(() => lazy().then((m) => m.panels.person())),
    },
  ],
  // Telegram `startapp=payroll`, `run_12`, `advances`, `adjustments`, `disputes`.
  deepLinks: {
    payroll: () => "payroll",
    run: (id) => (/^\d+$/.test(id) ? `payroll/runs/${id}` : "payroll"),
    advances: () => "payroll/advances",
    adjustments: () => "payroll/adjustments",
    disputes: () => "payroll/adjustments?tab=disputed",
  },
  messages: (language) => import(`./i18n/${language}.json`),
});
