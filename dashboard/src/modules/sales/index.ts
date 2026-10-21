/**
 * Sales and cash (plan §6.2 "Sales", package E): the sales overview with comparisons, cashier
 * shifts with a full shift drawer (photos, cash count, movements, verify), "where is my cash",
 * the cashier scorecard, monthly targets with pacing, single receipts and the tills and payment
 * methods setup. Kept light: pages, widgets, panels and the API all load on first use.
 */
import { Banknote, ClipboardCheck, Store, Target } from "@lucide/vue";
import { defineAsyncComponent } from "vue";

import { defineModule } from "@/core/modules";
import { counter } from "@/core/pulse";

import { routes } from "./routes";

export default defineModule({
  id: "sales",
  group: "money",
  order: 10,
  icon: Store,
  title: "sales.title",
  perm: ["sales.view", "sales.invoices"],
  feature: "sales",
  hotkey: "s",
  routes,
  nav: [
    { key: "overview", title: "sales.nav.overview", to: "sales", perm: "sales.view", exact: true },
    { key: "shifts", title: "sales.nav.shifts", to: "sales/shifts", perm: "sales.view", badge: counter("sales.to_verify") },
    { key: "cash", title: "sales.nav.cash", to: "sales/cash", perm: "sales.view" },
    { key: "cashiers", title: "sales.nav.cashiers", to: "sales/cashiers", perm: "sales.view" },
    { key: "targets", title: "sales.nav.targets", to: "sales/targets", perm: "sales.view" },
    { key: "entries", title: "sales.nav.entries", to: "sales/entries", perm: "sales.view" },
    { key: "setup", title: "sales.nav.setup", to: "sales/setup", perm: "sales.view" },
  ],
  // Shifts closed and waiting for a manager's check.
  badge: counter("sales.to_verify"),
  // Every `sales.*` pulse key (shifts, cash, setup, entries, targets, the badges) refreshes the module.
  invalidates: ["sales"],
  commands: (ctx) => [
    {
      id: "sales.verify",
      title: ctx.t("sales.cmd.verify"),
      icon: ClipboardCheck,
      keywords: ["shift", "verify", "smena", "tekshirish", "смена", "проверить", "kassa"],
      perm: "sales.manage",
      run: () => ctx.go("sales/shifts?view=verify"),
    },
    {
      id: "sales.movement",
      title: ctx.t("sales.cmd.movement"),
      icon: Banknote,
      keywords: ["cash", "payout", "handover", "naqd", "pul", "наличные", "выдача", "инкассация"],
      perm: "sales.manage",
      run: () => ctx.go("sales/cash?new=movement"),
    },
    {
      id: "sales.target",
      title: ctx.t("sales.cmd.target"),
      icon: Target,
      keywords: ["target", "plan", "reja", "план", "цель"],
      perm: "sales.manage",
      run: () => ctx.go("sales/targets?new=target"),
    },
  ],
  searchResults: {
    "sales.shift": defineAsyncComponent(() => import("./components/ShiftHit.vue")),
  },
  widgets: [
    {
      id: "sales.kpi.today",
      span: 1,
      order: 15,
      kind: "kpi",
      perm: "sales.view",
      feature: "sales",
      component: defineAsyncComponent(() => import("./widgets/SalesTodayWidget.vue")),
    },
  ],
  settings: [
    {
      id: "sales",
      title: "sales.settings.panel",
      perm: "sales.manage",
      feature: "sales",
      order: 40,
      component: defineAsyncComponent(() => import("./components/SalesSettingsPanel.vue")),
    },
    {
      id: "registers",
      title: "sales.registers.panel",
      perm: "sales.view",
      feature: "sales",
      order: 41,
      component: defineAsyncComponent(() => import("./components/RegistersPanel.vue")),
    },
    {
      id: "payment-methods",
      title: "sales.methods.panel",
      perm: "sales.view",
      feature: "sales",
      order: 42,
      component: defineAsyncComponent(() => import("./components/PaymentMethodsPanel.vue")),
    },
  ],
  // Telegram `startapp=shift_1042` opens the shift drawer.
  deepLinks: {
    shift: (id) => (/^\d+$/.test(id) ? `sales/shifts?shift=${id}` : "sales/shifts"),
  },
  messages: async () => {
    const [uz, ru, en] = await Promise.all([import("./i18n/uz.json"), import("./i18n/ru.json"), import("./i18n/en.json")]);
    return { uz: uz.default, ru: ru.default, en: en.default };
  },
});
