/**
 * The finance module (plan §6.1–§6.2, package D): money accounts, the ledger, debts (nasiya and
 * qarz), counterparties, reports, categories, rates and the period lock, plus a quick "Record"
 * dialog reachable from every page (`N`, the + in the top bar, palette commands). Package I adds
 * budgets, recurring bills, the payments calendar and claims to this module later.
 *
 * Kept tiny: pages, widgets, the dialog and the API load lazily.
 */
import { ArrowLeftRight, BookOpenCheck, ChartColumn, HandCoins, Landmark, Lock, TrendingDown, TrendingUp } from "@lucide/vue";
import { defineAsyncComponent } from "vue";

import { defineModule } from "@/core/modules";
import { counter } from "@/core/pulse";

import { openQuickAdd } from "./quickAdd";
import { routes } from "./routes";

const RECORD = "finance.record" as const;
const VIEW = "finance.view" as const;
const MANAGE = "finance.manage" as const;

export default defineModule({
  id: "finance",
  group: "money",
  order: 30,
  icon: Landmark,
  title: "finance.title",
  perm: ["finance.view", "finance.record", "finance.approve"],
  feature: "finance",
  hotkey: "f",
  routes,
  nav: [
    { key: "overview", title: "finance.nav.overview", to: "finance", perm: VIEW, exact: true },
    { key: "accounts", title: "finance.nav.accounts", to: "finance/accounts", perm: [VIEW, RECORD] },
    { key: "transactions", title: "finance.nav.transactions", to: "finance/transactions", perm: [VIEW, RECORD] },
    { key: "debts", title: "finance.nav.debts", to: "finance/debts", perm: VIEW, badge: counter("finance.overdue") },
    { key: "counterparties", title: "finance.nav.counterparties", to: "finance/counterparties", perm: VIEW },
    { key: "reports", title: "finance.nav.reports", to: "finance/reports", perm: VIEW },
    { key: "settings", title: "finance.nav.settings", to: "finance/settings", perm: MANAGE },
  ],
  badge: counter("finance.overdue"),
  // Every finance write bumps "finance.ledger"; debts also move "finance.overdue".
  invalidates: ["finance"],
  commands: (ctx) => [
    {
      id: "finance.record-expense",
      title: ctx.t("finance.cmd.expense"),
      icon: TrendingDown,
      shortcut: ["N"],
      keywords: ["xarajat", "расход", "spend", "chiqim"],
      perm: RECORD,
      run: () => openQuickAdd("expense"),
    },
    {
      id: "finance.record-income",
      title: ctx.t("finance.cmd.income"),
      icon: TrendingUp,
      keywords: ["daromad", "доход", "kirim"],
      perm: RECORD,
      run: () => openQuickAdd("income"),
    },
    {
      id: "finance.transfer",
      title: ctx.t("finance.cmd.transfer"),
      icon: ArrowLeftRight,
      keywords: ["o‘tkazma", "перевод", "inkassatsiya", "exchange", "dollar"],
      perm: RECORD,
      run: () => openQuickAdd("transfer"),
    },
    {
      id: "finance.new-debt",
      title: ctx.t("finance.cmd.debt"),
      icon: HandCoins,
      keywords: ["nasiya", "qarz", "долг"],
      perm: RECORD,
      run: () => ctx.go("finance/debts?new=1"),
    },
    {
      id: "finance.pnl",
      title: ctx.t("finance.cmd.pnl"),
      icon: ChartColumn,
      keywords: ["foyda", "прибыль", "profit", "P&L"],
      perm: VIEW,
      run: () => ctx.go("finance/reports/pnl"),
    },
    {
      id: "finance.close-period",
      title: ctx.t("finance.cmd.lock"),
      icon: Lock,
      keywords: ["yopish", "закрыть", "period"],
      perm: MANAGE,
      run: () => ctx.go("finance/settings/period"),
    },
    {
      id: "finance.opening",
      title: ctx.t("finance.cmd.opening"),
      icon: BookOpenCheck,
      keywords: ["qoldiq", "остаток", "opening"],
      perm: MANAGE,
      run: () => ctx.go("finance/accounts?setup=opening"),
    },
  ],
  // Ordered so the two KPI tiles fill the row of "Needs you" (30, span 2) and the chart pairs with
  // the activity stream (40, span 2): no holes in the four-column grid.
  widgets: [
    { id: "finance.kpi.cash_now", span: 1, order: 31, kind: "kpi", perm: VIEW, component: defineAsyncComponent(() => import("./widgets/CashNowWidget.vue")) },
    { id: "finance.kpi.expenses_mtd", span: 1, order: 32, kind: "kpi", perm: VIEW, component: defineAsyncComponent(() => import("./widgets/ExpensesWidget.vue")) },
    { id: "finance.chart.cash_flow_30d", span: 2, order: 42, kind: "chart", perm: VIEW, component: defineAsyncComponent(() => import("./widgets/CashFlowWidget.vue")) },
  ],
  settings: [
    { id: "finance", title: "finance.settings.panel", perm: MANAGE, order: 40, component: defineAsyncComponent(() => import("./components/FinanceSettingsPanel.vue")) },
  ],
  extensions: {
    "shell.topbar.end": [defineAsyncComponent(() => import("./components/QuickAddLauncher.vue"))],
  },
  deepLinks: {
    txn: (id) => (/^\d+$/.test(id) ? `finance/transactions?txn=${id}` : null),
    debt: (id) => (/^\d+$/.test(id) ? `finance/debts?debt=${id}` : null),
    finance: () => "finance",
  },
  messages: async () => {
    const [uz, ru, en] = await Promise.all([import("./i18n/uz.json"), import("./i18n/ru.json"), import("./i18n/en.json")]);
    return { uz: uz.default, ru: ru.default, en: en.default };
  },
});
