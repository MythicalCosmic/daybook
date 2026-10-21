// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { defineComponent, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";

import { toasts } from "@/components/useToast";
import { i18n, mergeModuleMessages, setLanguage } from "@/i18n";
import { customValue, rangeValue } from "@/lib/dateRange";
import { pageTitleFor } from "@/lib/usePageTitle";
import { useCompanyStore } from "@/stores/company";
import { useSessionStore } from "@/stores/session";
import { json, me } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import { financeApi, financeKeys, periodParams, useCategorize } from "../api";
import QuickAddDialog from "../components/QuickAddDialog.vue";
import TransactionDrawer from "../components/TransactionDrawer.vue";
import PnlTable from "../components/reports/PnlTable.vue";
import en from "../i18n/en.json";
import module from "../index";
import { baseTotal, colorFor, dayStyle, distinctColors, dropEmptyCompare, pickerOrder, topAccounts, trimLeadingEmpty, trimLeadingPeriods } from "../lib";
import type { Options, Pnl, PnlNode, Transaction, TransactionPage } from "../types";

interface Call {
  method: string;
  url: string;
  body: unknown;
}

const PREFIX = "/api/v1/owner/companies/1/finance/";

function stub(routes: Record<string, (call: Call) => Response>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const raw = init?.body;
      const body = raw instanceof FormData ? Object.fromEntries(raw.entries()) : raw ? JSON.parse(String(raw)) : undefined;
      const call = { method: init?.method ?? "GET", url: input, body };
      calls.push(call);
      const path = input.replace(PREFIX, "").split("?")[0]!;
      return routes[`${call.method} ${path}`]?.(call) ?? json({ detail: "Not found." }, 404);
    }),
  );
  return calls;
}

beforeEach(() => {
  mergeModuleMessages("finance", { en, ru: en, uz: en });
  toasts.splice(0, toasts.length);
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

// ─── API ───────────────────────────────────────────────────────────────────

describe("api", () => {
  it("sends a preset as a preset (the server compares the same days) and a custom range as dates", () => {
    const now = new Date("2026-10-21T09:00:00+05:00");
    expect(periodParams(rangeValue("month", "Asia/Tashkent", "prev", now))).toEqual({ preset: "month", compare: "prev" });
    expect(periodParams(rangeValue("year", "Asia/Tashkent", "none", now))).toEqual({ preset: "year" });
    expect(periodParams(customValue({ from: "2026-09-01", to: "2026-09-30" }, "year"))).toEqual({ from: "2026-09-01", to: "2026-09-30", compare: "year" });
  });

  it("calls the §4.7 endpoints with the bodies the backend expects", async () => {
    const calls = stub({
      "POST transactions/": () => json({ id: 5 }, 201),
      "PATCH transactions/5/": () => json({ id: 5 }),
      "POST transactions/bulk/": () => json({ results: [] }),
      "POST transactions/5/receipts/": () => json({ id: 9 }, 201),
      "DELETE transactions/5/receipts/9/": () => new Response(null, { status: 204 }),
      "POST debts/7/payments/": () => json({ id: 6 }, 201),
      "PUT debts/7/installments/": () => json([]),
      "POST rates/": () => json({ id: "company-1" }, 201),
      "POST settings/lock/": () => json({}),
      "GET reports/pnl/": () => json({}),
    });
    await financeApi.createTransaction(1, { kind: "expense", direction: "in", amount: "185000", occurred_on: "2026-10-21", account: 3, category: 4, counterparty: null, branch: null, description: "Non", receipt_ids: [9] });
    await financeApi.updateTransaction(1, 5, { category: 8 });
    await financeApi.bulk(1, [5, 6], "void", { reason: "Twice" });
    await financeApi.uploadReceipt(1, new File(["x"], "chek.jpg", { type: "image/jpeg" }), 5);
    await financeApi.removeReceipt(1, 5, 9);
    await financeApi.payDebt(1, 7, { amount: "1500000", paid_on: "2026-10-19", account: 3 });
    await financeApi.setInstallments(1, 7, [{ due_on: "2026-11-05", amount: "3200000" }]);
    await financeApi.setRate(1, "2026-10-21", "12170");
    await financeApi.lock(1, "2026-09-30");
    await financeApi.pnl(1, { preset: "year", group: "month", branch: [2, 3] });

    expect(calls.map((c) => `${c.method} ${c.url.replace(PREFIX, "")}`)).toEqual([
      "POST transactions/",
      "PATCH transactions/5/",
      "POST transactions/bulk/",
      "POST transactions/5/receipts/",
      "DELETE transactions/5/receipts/9/",
      "POST debts/7/payments/",
      "PUT debts/7/installments/",
      "POST rates/",
      "POST settings/lock/",
      "GET reports/pnl/?preset=year&group=month&branch=2&branch=3",
    ]);
    expect(calls[0]!.body).toMatchObject({ kind: "expense", amount: "185000", account: 3, category: 4, receipt_ids: [9] });
    expect(calls[2]!.body).toEqual({ ids: [5, 6], action: "void", reason: "Twice" });
    expect(calls[3]!.body).toHaveProperty("file");
    expect(calls[6]!.body).toEqual({ installments: [{ due_on: "2026-11-05", amount: "3200000" }] });
    expect(calls[7]!.body).toEqual({ currency: "USD", date: "2026-10-21", rate: "12170" });
    expect(calls[8]!.body).toEqual({ until: "2026-09-30" });
  });

  it("approves and rejects a waiting entry", async () => {
    const calls = stub({
      "POST transactions/5/approve/": () => json({ id: 5, status: "posted" }),
      "POST transactions/6/reject/": () => json({ id: 6, status: "rejected" }),
    });
    await financeApi.approveTransaction(1, 5);
    await financeApi.rejectTransaction(1, 6, "No receipt");
    expect(calls.map((c) => `${c.method} ${c.url.replace(PREFIX, "")}`)).toEqual(["POST transactions/5/approve/", "POST transactions/6/reject/"]);
    expect(calls[1]!.body).toEqual({ reason: "No receipt" });
  });

  it("registers in the money group with the finance pulse keys, widgets and deep links", () => {
    expect(module).toMatchObject({ id: "finance", group: "money", order: 30, feature: "finance", hotkey: "f", invalidates: ["finance"] });
    expect(module.widgets?.map((w) => w.id)).toEqual(["finance.kpi.cash_now", "finance.kpi.expenses_mtd", "finance.chart.cash_flow_30d"]);
    // The two KPI tiles fill the row of the inbox's "Needs you" (order 30, two columns) and the
    // chart pairs with the activity stream (40): a four-column grid without holes.
    expect(module.widgets?.map((w) => [w.order, w.span])).toEqual([
      [31, 1],
      [32, 1],
      [42, 2],
    ]);
    expect(module.deepLinks?.txn?.("12")).toBe("finance/transactions?txn=12");
    expect(module.deepLinks?.debt?.("x")).toBeNull();
    expect(financeKeys.of(1, "transactions", { page: 2 })).toEqual([1, "finance", "transactions", { page: 2 }]);
  });
});

// ─── Helpers ─────────────────────────────────────────────────────────────────

const node = (id: number, amounts: string[], children: PnlNode[] = []): PnlNode => ({
  id,
  name: `Category ${id}`,
  color: "",
  system_code: "",
  is_sensitive: false,
  amounts,
  total: String(amounts.reduce((sum, value) => sum + Number(value), 0)),
  own: amounts.map(() => "0.00"),
  own_total: "0.00",
  previous: null,
  children,
});

function pnl(periods: string[], income: PnlNode[], expense: PnlNode[]): Pnl {
  const sum = (nodes: PnlNode[], i: number) => String(nodes.reduce((total, n) => total + Number(n.amounts[i]), 0));
  const incomeAmounts = periods.map((_, i) => sum(income, i));
  const expenseAmounts = periods.map((_, i) => sum(expense, i));
  return {
    range: { from: `${periods[0]}-01`, to: "2026-10-21" },
    compare: null,
    currency: "UZS",
    group: "month",
    periods: periods.map((key) => ({ key, from: `${key}-01`, to: `${key}-28` })),
    income: { nodes: income, amounts: incomeAmounts, total: String(incomeAmounts.reduce((a, b) => a + Number(b), 0)), previous: null },
    expense: { nodes: expense, amounts: expenseAmounts, total: String(expenseAmounts.reduce((a, b) => a + Number(b), 0)), previous: null },
    profit: { amounts: periods.map((_, i) => String(Number(incomeAmounts[i]) - Number(expenseAmounts[i]))), total: "0", previous: null },
    margin: { amounts: periods.map(() => null), total: null, previous: null },
  };
}

describe("lib", () => {
  it("offers cash desks before banks and people's purses, the last used and the branch's own first", () => {
    const accounts = [
      { id: 1, kind: "employee" as const, branch_id: 1 },
      { id: 2, kind: "bank" as const, branch_id: null },
      { id: 3, kind: "cash" as const, branch_id: 2 },
      { id: 4, kind: "cash" as const, branch_id: 1 },
    ];
    expect(pickerOrder(accounts).map((a) => a.id)).toEqual([3, 4, 2, 1]);
    expect(pickerOrder(accounts, { branch: 1 }).map((a) => a.id)).toEqual([4, 1, 3, 2]);
    expect(pickerOrder(accounts, { id: 2, branch: 1 }).map((a) => a.id)).toEqual([2, 4, 1, 3]);
  });

  it("drops the empty months before the books began, keeping totals and at least one column", () => {
    const data = pnl(["2026-01", "2026-02", "2026-03"], [node(1, ["0.00", "100.00", "50.00"], [node(11, ["0.00", "100.00", "50.00"])])], [node(2, ["0.00", "40.00", "0.00"])]);
    const trimmed = trimLeadingPeriods(data);
    expect(trimmed.periods.map((p) => p.key)).toEqual(["2026-02", "2026-03"]);
    expect(trimmed.income.nodes[0]!.amounts).toEqual(["100.00", "50.00"]);
    expect(trimmed.income.nodes[0]!.children[0]!.amounts).toEqual(["100.00", "50.00"]);
    expect(trimmed.profit.amounts).toEqual(["60", "50"]);
    expect(trimmed.income.total).toBe(data.income.total);
    const empty = pnl(["2026-01", "2026-02"], [node(1, ["0.00", "0.00"])], []);
    expect(trimLeadingPeriods(empty).periods.map((p) => p.key)).toEqual(["2026-02"]);
  });

  it("hides a comparison with a period that had nothing booked, and keeps a real one", () => {
    const data = pnl(["2026-09", "2026-10"], [node(1, ["900.00", "700.00"])], [node(2, ["400.00", "300.00"])]);
    const empty: Pnl = {
      ...data,
      compare: { from: "2025-09-01", to: "2025-10-21" },
      income: { ...data.income, previous: "0.00", nodes: data.income.nodes.map((n) => ({ ...n, previous: "0.00" })) },
      expense: { ...data.expense, previous: "0.00" },
      profit: { ...data.profit, previous: "0.00" },
    };
    const dropped = dropEmptyCompare(empty);
    expect(dropped.compare).toBeNull();
    expect(dropped.income.previous).toBeNull();
    expect(dropped.income.nodes[0]!.previous).toBeNull();
    expect(dropped.profit.previous).toBeNull();
    const real: Pnl = { ...empty, expense: { ...empty.expense, previous: "120.00" } };
    expect(dropEmptyCompare(real)).toBe(real);
  });

  it("starts a series where the money started, keeping at least a week", () => {
    const zero = { income: "0.00", expense: "0.00" };
    const days = [zero, zero, zero, ...Array.from({ length: 8 }, (_, i) => ({ income: `${i + 1}.00`, expense: "0.00" }))];
    const series = days.map((point, i) => ({ ...point, date: String(i) }));
    expect(trimLeadingEmpty(series).map((p) => p.date)).toEqual(["3", "4", "5", "6", "7", "8", "9", "10"]);
    const quiet = Array.from({ length: 9 }, (_, i) => ({ ...zero, date: String(i) }));
    expect(trimLeadingEmpty(quiet)).toHaveLength(7);
  });

  it("writes the year only for days outside this year", () => {
    const now = new Date("2026-10-21T12:00:00Z");
    expect(dayStyle("2026-09-09", now)).toBe("short");
    expect(dayStyle("2027-08-23", now)).toBe("medium");
  });

  it("turns a stored swatch into its theme token, so it follows dark mode", () => {
    expect(colorFor(5, "#C67139")).toBe("var(--c-chart-1)");
    expect(colorFor(5, "#3f8a83")).toBe("var(--c-chart-6)");
    expect(colorFor(5, "#123456")).toBe("#123456");
    expect(colorFor(9, "")).toBe("var(--c-chart-2)");
  });

  it("gives the slices of one chart distinct colours, the biggest keeping their own", () => {
    // Ids 1 and 9 share chart-2, id 7 lands on the gray of "Other", 3 has its own swatch.
    const rows = [{ id: 1 }, { id: 9 }, { id: 3, color: "#d1a040" }, { id: 7 }];
    expect(distinctColors(rows)).toEqual(["var(--c-chart-2)", "var(--c-chart-1)", "var(--c-chart-4)", "var(--c-chart-3)"]);
    // A swatch and the token it equals count as the same colour.
    expect(distinctColors([{ id: 0 }, { id: 2, color: "#c67139" }])).toEqual(["var(--c-chart-1)", "var(--c-chart-3)"]);
  });

  it("lists where the money is: biggest in the base currency first, overdrawn ones by size, empty ones last", () => {
    const accounts = [
      { id: 1, balance: "0.00", base: "0.00" },
      { id: 2, balance: "923000500.00", base: "923000500.00" },
      { id: 3, balance: "8350.00", base: "101604052.50" },
      { id: 4, balance: "-2000000.00", base: "-2000000.00" },
      { id: 5, balance: "1360000.00", base: null },
    ];
    expect(topAccounts(accounts, 4).map((a) => a.id)).toEqual([2, 3, 4, 5]);
  });

  it("adds a group of accounts up in the base currency, or not at all without a value", () => {
    const rows = [
      { currency: "UZS", balance: "1360000.00", base: "1360000.00" },
      { currency: "USD", balance: "8350.00", base: "101604052.50" },
    ];
    expect(baseTotal(rows, "UZS")).toBe("102964052.50");
    expect(baseTotal([...rows, { currency: "USD", balance: "10.00", base: null }], "UZS")).toBeNull();
  });
});

// ─── Components ──────────────────────────────────────────────────────────────

describe("PnlTable", () => {
  it("opens a parent to its subcategories and links every cell to the entries behind it", async () => {
    const data = pnl(["2026-09", "2026-10"], [node(1, ["900000.00", "700000.00"], [node(11, ["800000.00", "650000.00"]), node(12, ["100000.00", "50000.00"])])], [node(2, ["400000.00", "300000.00"])]);
    const app = await testApp("/c/1/finance/reports/pnl");
    const { wrapper } = mountWithProviders(PnlTable, { plugins: app.plugins, props: { data } });
    expect(wrapper.text()).toContain("Category 1");
    expect(wrapper.text()).not.toContain("Category 11");
    const toggle = wrapper.find('button[aria-expanded="false"]');
    await toggle.trigger("click");
    expect(wrapper.text()).toContain("Category 11");
    expect(wrapper.find('button[aria-expanded="true"]').exists()).toBe(true);
    const hrefs = wrapper.findAll("a").map((a) => a.attributes("href"));
    expect(hrefs).toContain("/c/1/finance/transactions?from=2026-09-01&to=2026-09-28&category=11");
    expect(hrefs).toContain("/c/1/finance/transactions?from=2026-09-01&to=2026-10-21&category=1");
  });
});

const options = (): Options =>
  ({
    base_currency: "UZS",
    today: "2026-10-21",
    accounts: [
      { id: 8, name: "Bekzod's purse", kind: "employee", currency: "UZS", branch_id: 1 },
      { id: 3, name: "Kassa", kind: "cash", currency: "UZS", branch_id: 1 },
    ],
    transfer_targets: [],
    members: [],
    branches: [{ id: 1, name: "Chilonzor", code: "CHL" }],
    projects: [],
    receipt_required_over: "5000000",
    locked_until: null,
    rate: { rate: "12168.15", stale: false, source: "cbu" },
  }) as unknown as Options;

describe("QuickAddDialog", () => {
  it("records an expense on the cash desk (not a person's purse) with the picked category", async () => {
    const calls = stub({
      "GET options/": () => json(options()),
      "GET categories/": () => json([{ id: 4, name: "Bread", kind: "expense", color: "", icon: "", is_system: false, system_code: "", is_active: true, is_capex: false, is_sensitive: false, parent: null, children: [] }]),
      "POST transactions/": () => json({ id: 77, amount: "-185000.00", currency: "UZS" }, 201),
    });
    const app = await testApp("/c/1/finance/transactions");
    const { inner } = mountWithProviders(QuickAddDialog, { plugins: app.plugins, props: { open: true, request: { mode: "expense", amount: "185000", category: 4 } } });
    await flushPromises();
    await flushPromises();
    document.querySelector<HTMLButtonElement>('[data-testid="quick-save"]')!.click();
    await flushPromises();
    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toMatchObject({ kind: "expense", amount: "185000", account: 3, category: 4, occurred_on: "2026-10-21", receipt_ids: [] });
    expect(inner.emitted("update:open")?.at(-1)).toEqual([false]);
    expect(toasts.at(-1)?.title).toBe(en["finance.quick.saved.expense"]);
  });

  it("asks for a receipt photo above the company's limit and shows server field errors", async () => {
    stub({
      "GET options/": () => json(options()),
      "GET categories/": () => json([]),
      "POST transactions/": () => json({ amount: ["Attach a receipt: expenses over 5,000,000 need one."] }, 400),
    });
    const app = await testApp("/c/1/finance/transactions");
    mountWithProviders(QuickAddDialog, { plugins: app.plugins, props: { open: true, request: { mode: "expense", amount: "6000000", category: 4 } } });
    await flushPromises();
    await flushPromises();
    expect(document.body.textContent).toContain(en["finance.quick.needsReceipt"]);
    document.querySelector<HTMLButtonElement>('[data-testid="quick-save"]')!.click();
    await flushPromises();
    expect(document.body.textContent).toContain("Attach a receipt: expenses over 5,000,000 need one.");
  });
});

const waiting = (overrides: Partial<Transaction> = {}): Transaction =>
  ({
    id: 5,
    kind: "expense",
    kind_label: "Expense",
    status: "pending",
    status_label: "Waiting for approval",
    occurred_on: "2026-10-20",
    account: { id: 8, name: "Bekzod's purse", kind: "employee", currency: "UZS" },
    amount: "-450000.00",
    currency: "UZS",
    rate: "1.000000",
    rate_stale: false,
    base_amount: "-450000.00",
    category: { id: 4, name: "Fuel", kind: "expense", color: "", parent_name: "Transport" },
    counterparty: null,
    membership: null,
    branch: null,
    project: null,
    debt_id: null,
    transfer_id: null,
    is_contra: false,
    description: "Benzin",
    source: null,
    created_by: "Nigora Azimova",
    created_at: "2026-10-20T10:00:00+05:00",
    approved_by: null,
    approved_at: null,
    voided_by: null,
    voided_at: null,
    void_reason: "",
    receipts: [],
    masked: false,
    is_manual: true,
    can_edit: true,
    can_void: true,
    can_approve: true,
    ...overrides,
  }) as Transaction;

describe("TransactionDrawer", () => {
  it("offers approve and reject on an entry waiting for approval, and approves it", async () => {
    const calls = stub({
      "GET transactions/5/": () => json(waiting()),
      "POST transactions/5/approve/": () => json(waiting({ status: "posted", can_approve: false })),
    });
    const app = await testApp("/c/1/finance/transactions?txn=5");
    mountWithProviders(TransactionDrawer, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    expect(document.body.textContent).toContain(en["finance.tx.waitingTitle"]);
    const buttons = [...document.querySelectorAll<HTMLButtonElement>("button")];
    expect(buttons.some((b) => b.textContent?.includes(en["finance.tx.reject"]))).toBe(true);
    expect(buttons.some((b) => b.textContent?.includes(en["finance.tx.void"]))).toBe(false);
    buttons.find((b) => b.textContent?.trim() === en["finance.tx.approve"])!.click();
    await flushPromises();
    expect(calls.some((c) => c.method === "POST" && c.url.endsWith("transactions/5/approve/"))).toBe(true);
    expect(toasts.at(-1)?.title).toBe(en["finance.tx.approved"]);
  });

  it("shows no decision buttons to someone who may not decide", async () => {
    stub({ "GET transactions/5/": () => json(waiting({ can_approve: false })) });
    const app = await testApp("/c/1/finance/transactions?txn=5");
    mountWithProviders(TransactionDrawer, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    expect(document.body.textContent).toContain(en["finance.tx.waitingOther"]);
    const labels = [...document.querySelectorAll<HTMLButtonElement>("button")].map((b) => b.textContent?.trim());
    expect(labels).not.toContain(en["finance.tx.approve"]);
  });
});

describe("useCategorize", () => {
  it("shows the new category at once and puts the old one back when the server refuses", async () => {
    // The server answers only when the test says so, to look at the table while the request is out.
    let answer: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => (answer = resolve));
    vi.stubGlobal(
      "fetch",
      vi.fn(() => gate.then(() => json({ detail: "The books are closed up to 30 Sep 2026." }, 400))),
    );
    const app = await testApp("/c/1/finance/transactions");
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
    const row = { id: 5, category: { id: 4, name: "Bread", kind: "expense", color: "", parent_name: null } } as unknown as Transaction;
    const key = financeKeys.of(1, "transactions", { page: 1 });
    client.setQueryData<TransactionPage>(key, { count: 1, next: null, previous: null, results: [row] } as TransactionPage);
    let mutation: ReturnType<typeof useCategorize> | null = null;
    const Host = defineComponent({
      setup() {
        mutation = useCategorize();
        return () => h("div");
      },
    });
    mount(Host, { global: { plugins: [app.pinia, app.router, [VueQueryPlugin, { queryClient: client }]] } });
    const pending = mutation!.mutateAsync({ row, category: { id: 9, name: "Packaging", color: "", parent_name: null } }).catch(() => null);
    await flushPromises();
    expect(client.getQueryData<TransactionPage>(key)?.results[0]?.category?.id).toBe(9);
    answer();
    await pending;
    await flushPromises();
    expect(client.getQueryData<TransactionPage>(key)?.results[0]?.category?.id).toBe(4);
  });
});

describe("CounterpartyDetailPage", () => {
  it("names the breadcrumb after the counterparty and shows its kind in the list's colour", async () => {
    const party = {
      id: 7,
      name: "Barakat Kafe",
      kind: "customer",
      kind_label: "Customer",
      phone: "+998977001234",
      tin: "",
      contact_person: "Odil aka",
      telegram_username: "",
      address: "",
      bank_details: "",
      notes: "",
      default_category: null,
      credit_limit: null,
      credit_blocked: false,
      birthday: null,
      tags: [],
      is_active: true,
      owes_us: "11200000.00",
      we_owe: "0.00",
      overdue: "6300000.00",
      last_activity: "2026-10-19",
      created_at: "2026-08-20T10:00:00Z",
    };
    stub({ "GET counterparties/7/": () => json({ counterparty: party, totals: { income: "11950000.00", expense: "0.00", money_in: "4700000.00", money_out: "0.00" }, debts: [], transactions: [] }) });
    const pinia = createPinia();
    setActivePinia(pinia);
    useSessionStore().me = me();
    useCompanyStore().setCurrent(1);
    setLanguage("en");
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/c/:companyId/finance/counterparties/:partyId", component: { render: () => null } }] });
    await router.push("/c/1/finance/counterparties/7");
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const CounterpartyDetailPage = (await import("../pages/CounterpartyDetailPage.vue")).default;
    const { wrapper } = mountWithProviders(CounterpartyDetailPage, { plugins: [pinia, router, i18n, [VueQueryPlugin, { queryClient: client }]] });
    await flushPromises();
    await flushPromises();
    expect(pageTitleFor(router.currentRoute.value)).toBe("Barakat Kafe");
    const pill = wrapper.findAll("span").find((span) => span.text() === "Customer");
    expect(pill?.classes()).toContain("text-success");
    wrapper.unmount();
  });
});
