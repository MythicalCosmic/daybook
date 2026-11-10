/**
 * The finance module (plan §6.1–§6.2, package D): money accounts, the ledger, debts (nasiya and
 * qarz), counterparties, reports, categories, rates and the period lock, plus a quick "Record"
 * dialog reachable from every page (`N`, the + in the top bar, palette commands). Package I adds
 * money planning: paying distributors, staff expense claims, the payments calendar with the cash
 * forecast, recurring bills with the tax calendar, budgets, and the tax regime in the settings.
 *
 * Kept tiny: pages, widgets, the dialog and the API load lazily.
 */
import { ArrowLeftRight, BookOpenCheck, CalendarClock, ChartColumn, HandCoins, Landmark, Lock, PiggyBank, ReceiptText, TrendingDown, TrendingUp, Truck } from "@lucide/vue";
import { defineAsyncComponent } from "vue";

import { defineModule } from "@/core/modules";
import { counter } from "@/core/pulse";

import { openQuickAdd } from "./quickAdd";
import { routes } from "./routes";

const RECORD = "finance.record" as const;
const VIEW = "finance.view" as const;
const MANAGE = "finance.manage" as const;
const APPROVE = "finance.approve" as const;

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
    { key: "payables", title: "finance.nav.payables", to: "finance/payables", perm: VIEW },
    { key: "claims", title: "finance.nav.claims", to: "finance/claims", perm: [APPROVE, VIEW], badge: counter("finance.claims") },
    { key: "calendar", title: "finance.nav.calendar", to: "finance/calendar", perm: VIEW },
    { key: "recurring", title: "finance.nav.recurring", to: "finance/recurring", perm: VIEW },
    { key: "budgets", title: "finance.nav.budgets", to: "finance/budgets", perm: VIEW },
    { key: "counterparties", title: "finance.nav.counterparties", to: "finance/counterparties", perm: VIEW },
    { key: "reports", title: "finance.nav.reports", to: "finance/reports", perm: VIEW },
    { key: "settings", title: "finance.nav.settings", to: "finance/settings", perm: MANAGE },
    // v11: "Mening pulim", a sidebar row of its own in Money, right after Finance.
    {
      key: "myMoney",
      title: "finance.nav.myMoney",
      to: "finance/my-money",
      perm: MANAGE,
      row: { key: "finance.mymoney", title: "finance.nav.myMoney", icon: PiggyBank, group: "money", order: 31 },
    },
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
    // Recording a debt happens on the debts page, which needs finance.view as well.
    ...(ctx.can(VIEW)
      ? [
          {
            id: "finance.new-debt",
            title: ctx.t("finance.cmd.debt"),
            icon: HandCoins,
            keywords: ["nasiya", "qarz", "долг"],
            perm: RECORD,
            run: () => ctx.go("finance/debts?new=1"),
          },
        ]
      : []),
    {
      id: "finance.pnl",
      title: ctx.t("finance.cmd.pnl"),
      icon: ChartColumn,
      keywords: ["foyda", "прибыль", "profit", "P&L"],
      perm: VIEW,
      run: () => ctx.go("finance/reports/pnl"),
    },
    // Paying distributors happens on the payables page, which needs finance.view as well.
    ...(ctx.can(VIEW)
      ? [
          {
            id: "finance.pay-distributors",
            title: ctx.t("finance.cmd.payDistributors"),
            icon: Truck,
            keywords: ["distribyutor", "дистрибьютор", "поставщик", "kreditor", "payables", "to‘lash"],
            perm: RECORD,
            run: () => ctx.go("finance/payables"),
          },
        ]
      : []),
    {
      id: "finance.upcoming",
      title: ctx.t("finance.cmd.upcoming"),
      icon: CalendarClock,
      keywords: ["kalendar", "календарь", "prognoz", "прогноз", "forecast", "to‘lovlar"],
      perm: VIEW,
      run: () => ctx.go("finance/calendar"),
    },
    {
      id: "finance.budgets",
      title: ctx.t("finance.cmd.budgets"),
      icon: PiggyBank,
      keywords: ["byudjet", "бюджет", "budget", "limit", "лимит"],
      perm: VIEW,
      run: () => ctx.go("finance/budgets"),
    },
    {
      id: "finance.claims",
      title: ctx.t("finance.cmd.claims"),
      icon: ReceiptText,
      keywords: ["xarajat", "чек", "возмещение", "claim", "avans hisoboti"],
      perm: [APPROVE, VIEW],
      run: () => ctx.go("finance/claims"),
    },
    {
      id: "finance.close-period",
      title: ctx.t("finance.cmd.lock"),
      icon: Lock,
      keywords: ["yopish", "закрыть", "period"],
      perm: MANAGE,
      run: () => ctx.go("finance/settings/period"),
    },
    // Opening balances are set on the accounts page, which needs finance.view or finance.record.
    ...(ctx.can([VIEW, RECORD])
      ? [
          {
            id: "finance.opening",
            title: ctx.t("finance.cmd.opening"),
            icon: BookOpenCheck,
            keywords: ["qoldiq", "остаток", "opening"],
            perm: MANAGE,
            run: () => ctx.go("finance/accounts?setup=opening"),
          },
        ]
      : []),
  ],
  // Ordered so the two KPI tiles fill the row of "Needs you" (30, span 2) and the chart pairs with
  // the activity stream (40, span 2): no holes in the four-column grid.
  widgets: [
    { id: "finance.kpi.cash_now", span: 1, order: 31, kind: "kpi", perm: VIEW, component: defineAsyncComponent(() => import("./widgets/CashNowWidget.vue")) },
    { id: "finance.kpi.expenses_mtd", span: 1, order: 32, kind: "kpi", perm: VIEW, component: defineAsyncComponent(() => import("./widgets/ExpensesWidget.vue")) },
    { id: "finance.chart.cash_flow_30d", span: 2, order: 42, kind: "chart", perm: VIEW, component: defineAsyncComponent(() => import("./widgets/CashFlowWidget.vue")) },
    // After the cash-flow chart: with the other two-column cards of that band it makes full rows.
    { id: "finance.budget_burn", span: 2, order: 43, kind: "card", perm: VIEW, component: defineAsyncComponent(() => import("./widgets/BudgetBurnWidget.vue")) },
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
    // Package I: a recurring bill's reminder ("recurring_12"), the claims waiting, payables, the calendar, budgets.
    recurring: (id) => (/^\d+$/.test(id) ? `finance/recurring?rule=${id}` : "finance/recurring"),
    claims: () => "finance/claims",
    payables: () => "finance/payables",
    upcoming: () => "finance/calendar",
    budgets: () => "finance/budgets",
  },
  messages: (language) => import(`./i18n/${language}.json`),
});
