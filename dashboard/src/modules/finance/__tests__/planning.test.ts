// Package I (money planning): the pure helpers behind budgets, recurring rules, the payments
// calendar, payables and claims, the endpoints' bodies, and the pages that decide something.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { toasts } from "@/components/useToast";
import type { Perm } from "@/core/perms";
import { mergeModuleMessages } from "@/i18n";
import { dec } from "@/lib/decimal";
import { useSessionStore } from "@/stores/session";
import { company, json, me } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import { financeApi } from "../api";
import en from "../i18n/en.json";
import module from "../index";
import {
  bankTransferWarning,
  bucketTotals,
  budgetChanges,
  budgetLines,
  budgetShare,
  budgetStatus,
  draftBudgetTotal,
  forecastHeadline,
  groupUpcoming,
  isMonth,
  monthPace,
  ruleDayFrom,
  ruleGroup,
  scheduleText,
  shiftMonth,
  taxSetsInOrder,
  upcomingTarget,
  validPayment,
} from "../lib";
import type { BudgetRow, Options, PayableDebt, TaxTemplateSet, UpcomingItem } from "../types";

vi.setConfig({ testTimeout: 20_000 });

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

const t = (key: string, params: Record<string, unknown> = {}) =>
  String((en as Record<string, string>)[key] ?? (key.startsWith("common.weekday.long.") ? ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][Number(key.slice(-1))] : key))
    .split(" | ")[0]!
    .replace(/\{(\w+)\}/g, (_, name: string) => String(params[name] ?? `{${name}}`));

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

const options = (): Options =>
  ({
    base_currency: "UZS",
    today: "2026-11-06",
    accounts: [
      { id: 3, name: "Kassa", kind: "cash", currency: "UZS", branch_id: 1 },
      { id: 5, name: "Asosiy bank hisobi", kind: "bank", currency: "UZS", branch_id: null },
    ],
    transfer_targets: [],
    members: [],
    branches: [{ id: 1, name: "Chilonzor", code: "CHL" }],
    projects: [],
    receipt_required_over: null,
    locked_until: null,
    rate: { rate: "12168.15", stale: false, source: "cbu" },
  }) as unknown as Options;

const row = (id: number, name: string, budget: string | null, actual: string, parent: number | null = null, extra: Partial<BudgetRow> = {}): BudgetRow => ({
  category: { id, name, kind: "expense", color: "", parent_id: parent },
  budget,
  actual,
  share: budget ? (Number(actual) / Number(budget)).toFixed(2) : null,
  status: budgetStatus(budget, actual),
  ...extra,
});

const item = (overrides: Partial<UpcomingItem>): UpcomingItem => ({
  key: "rule:1:2026-11-10",
  kind: "bill",
  title: "Ijara",
  subtitle: "",
  date: "2026-11-10",
  amount: "12000000.00",
  currency: "UZS",
  direction: "out",
  overdue: false,
  estimate: false,
  rule_id: 1,
  debt_id: null,
  url: "/c/1/finance/recurring?rule=1",
  ...overrides,
});

// ─── Budgets ─────────────────────────────────────────────────────────────────

describe("budget helpers", () => {
  it("steps months across years and knows a month when it sees one", () => {
    expect(shiftMonth("2026-01", -1)).toBe("2025-12");
    expect(shiftMonth("2026-11", 2)).toBe("2027-01");
    expect(shiftMonth("2026-11", 0)).toBe("2026-11");
    expect(isMonth("2026-11")).toBe(true);
    expect(isMonth("2026-13")).toBe(false);
    expect(isMonth("2026-11-01")).toBe(false);
  });

  it("warns from exactly 80 % and calls 100 % over, as the server does", () => {
    expect(budgetStatus("1000000", "799999.99")).toBe("ok");
    expect(budgetStatus("1000000", "800000")).toBe("warning");
    expect(budgetStatus("1000000", "999999.99")).toBe("warning");
    expect(budgetStatus("1000000", "1000000.00")).toBe("over");
    expect(budgetStatus(null, "500")).toBe("none");
    expect(budgetStatus("", "500")).toBe("none");
    expect(budgetStatus("0", "500")).toBe("none");
    expect(budgetShare("3000000.00", "2460000.00")).toBeCloseTo(0.82);
    expect(budgetShare(null, "1")).toBeNull();
  });

  it("lists each category with its subcategories right under it, and never drops an orphan", () => {
    const rows = [row(10, "Kommunal", null, "0"), row(2, "Ijara › Yunusobod", null, "0", 1), row(1, "Ijara", "3000000", "2460000"), row(3, "Ijara › Chilonzor", null, "0", 1), row(9, "Lost child", null, "0", 99)];
    const lines = budgetLines(rows);
    expect(lines.map((line) => [line.row.category.id, line.depth])).toEqual([
      [10, 0],
      [1, 0],
      [2, 1],
      [3, 1],
      [9, 0],
    ]);
    expect(lines.find((line) => line.row.category.id === 1)?.parent).toBe(true);
  });

  it("sends only budgets that really changed (null removes one) and moves the total by them", () => {
    const rows = [row(1, "Ijara", "3000000.00", "2460000.00"), row(2, "Kommunal", null, "0.00"), row(3, "Internet", "500000.00", "0.00")];
    const changes = budgetChanges(rows, { 1: "3000000", 2: "1200000", 3: "" });
    expect(changes).toEqual([
      { category: 2, amount: "1200000" },
      { category: 3, amount: null },
    ]);
    expect(draftBudgetTotal("3500000.00", rows, changes)).toBe("4200000.00");
    expect(budgetChanges(rows, {})).toEqual([]);
    // Nothing typed: the server's total stands.
    expect(draftBudgetTotal("3500000.00", rows, [])).toBe("3500000.00");
  });

  it("adds a subcategory's budget to the total only while its parent has none, as the server does", () => {
    const rows = [row(1, "Ijara", null, "2460000.00"), row(2, "Ijara › Chilonzor", "1000000.00", "500000.00", 1), row(3, "Ijara › Yunusobod", null, "0.00", 1)];
    expect(draftBudgetTotal("1000000.00", rows, [{ category: 3, amount: "800000" }])).toBe("1800000.00");
    // A budget on the parent covers its subcategories: theirs stop counting.
    expect(draftBudgetTotal("1000000.00", rows, [{ category: 1, amount: "3000000" }])).toBe("3000000.00");
  });

  it("puts the pace tick where the month is: day 6 of 30 is 20 %", () => {
    expect(monthPace(24, 30)).toBeCloseTo(20);
    expect(monthPace(0, 30)).toBe(100);
    expect(monthPace(30, 30)).toBe(0);
    expect(monthPace(5, 0)).toBe(0);
  });
});

// ─── Recurring rules ──────────────────────────────────────────────────────────

describe("recurring helpers", () => {
  const rule = { frequency: "monthly" as const, interval: 1, day: 25, starts_on: "2026-03-10" };
  const day = (value: string) => `[${value}]`;

  it("says a schedule in words: day of month, last day, weekdays, every N, a yearly date from the start month", () => {
    expect(scheduleText(rule, t, day)).toBe("Monthly, day 25");
    expect(scheduleText({ ...rule, day: 31 }, t, day)).toBe("Monthly, last day");
    expect(scheduleText({ ...rule, interval: 2 }, t, day)).toBe("Every 2 months, day 25");
    expect(scheduleText({ ...rule, frequency: "weekly", day: 1 }, t, day)).toBe("Weekly: Monday");
    expect(scheduleText({ ...rule, frequency: "weekly", day: 7, interval: 2 }, t, day)).toBe("Every 2 weeks: Sunday");
    expect(scheduleText({ ...rule, frequency: "quarterly" }, t, day)).toBe("Quarterly, day 25");
    // A yearly rule falls in its start's month; day 31 of February is its last day.
    expect(scheduleText({ ...rule, frequency: "yearly" }, t, day)).toBe("Yearly, [2026-03-25]");
    expect(scheduleText({ ...rule, frequency: "yearly", day: 31, starts_on: "2026-02-01" }, t, day)).toBe("Yearly, [2026-02-28]");
  });

  it("files taxes apart from bills and reads a rule's day off a date", () => {
    expect(ruleGroup({ mode: "bill", is_tax: true })).toBe("tax");
    expect(ruleGroup({ mode: "bill", is_tax: false })).toBe("bill");
    expect(ruleGroup({ mode: "auto", is_tax: false })).toBe("auto");
    // 6 November 2026 is a Friday.
    expect(ruleDayFrom("2026-11-06", "weekly")).toBe(5);
    expect(ruleDayFrom("2026-11-08", "weekly")).toBe(7);
    expect(ruleDayFrom("2026-11-06", "monthly")).toBe(6);
  });

  it("lists the company's own regime first in the tax calendar", () => {
    const set = (key: TaxTemplateSet["key"], current: boolean): TaxTemplateSet => ({ key, label: key, current, note: "", items: [] });
    expect(taxSetsInOrder([set("turnover", false), set("vat", true), set("vat_simplified", false)]).map((s) => s.key)).toEqual(["vat", "turnover", "vat_simplified"]);
  });
});

// ─── Calendar and forecast ─────────────────────────────────────────────────────

describe("calendar helpers", () => {
  it("groups upcoming payments by day with everything overdue first, and adds each side up", () => {
    const groups = groupUpcoming(
      [
        item({ key: "a", date: "2026-11-10", amount: "1000.00" }),
        item({ key: "b", date: "2026-11-03", overdue: true, amount: "500.00" }),
        item({ key: "c", date: "2026-11-10", direction: "in", kind: "receivable", amount: "300.00" }),
        item({ key: "d", date: "2026-11-08", amount: null }),
        item({ key: "e", date: "2026-11-10", amount: "50.00", currency: "USD" }),
        item({ key: "f", date: "2026-11-01", overdue: true, amount: "200.00" }),
      ],
      "UZS",
    );
    expect(groups.map((group) => group.key)).toEqual(["overdue", "2026-11-08", "2026-11-10"]);
    expect(groups[0]!.items.map((entry) => entry.key)).toEqual(["f", "b"]);
    expect(groups[0]!.out).toBe("700.00");
    // An unknown amount and a dollar debt show on their own lines, not in the day's so‘m total.
    expect(groups[1]!.out).toBe("0.00");
    expect(groups[2]).toMatchObject({ day: "2026-11-10", out: "1000.00", in: "300.00" });
  });

  it("sends each item where it is dealt with", () => {
    const base = "/c/1/finance";
    expect(upcomingTarget(item({ kind: "bill" }), base, true)).toEqual({ type: "pay", ruleId: 1 });
    expect(upcomingTarget(item({ kind: "tax" }), base, false)).toEqual({ type: "link", to: "/c/1/finance/recurring?rule=1" });
    expect(upcomingTarget(item({ kind: "auto" }), base, true)).toEqual({ type: "link", to: "/c/1/finance/recurring?rule=1" });
    expect(upcomingTarget(item({ kind: "payable", rule_id: null, debt_id: 44 }), base, true)).toEqual({ type: "link", to: "/c/1/finance/payables?select=44" });
    expect(upcomingTarget(item({ kind: "receivable", rule_id: null, debt_id: 45 }), base, true)).toEqual({ type: "link", to: "/c/1/finance/debts?direction=receivable&debt=45" });
    expect(upcomingTarget(item({ kind: "payroll", rule_id: null, url: "/c/1/payroll/runs/3" }), base, true)).toEqual({ type: "link", to: "/c/1/payroll/runs/3" });
    expect(upcomingTarget(item({ kind: "payroll", rule_id: null, url: "" }), base, true)).toEqual({ type: "none" });
  });

  it("headlines the first day below zero, else the lowest point", () => {
    const points = [
      { date: "2026-11-06", balance: "5000.00", in: "0", out: "0" },
      { date: "2026-11-25", balance: "-1200.00", in: "0", out: "6200" },
      { date: "2026-11-26", balance: "-3000.00", in: "0", out: "1800" },
    ];
    expect(forecastHeadline({ below_zero_on: "2026-11-25", low: { date: "2026-11-26", balance: "-3000.00" }, points })).toEqual({ kind: "below", date: "2026-11-25", balance: "-1200.00" });
    expect(forecastHeadline({ below_zero_on: null, low: { date: "2026-11-20", balance: "12400000.00" }, points: [] })).toEqual({ kind: "low", date: "2026-11-20", balance: "12400000.00" });
  });
});

// ─── Payables ──────────────────────────────────────────────────────────────────

const payable = (id: number, overrides: Partial<PayableDebt> = {}): PayableDebt =>
  ({
    id,
    direction: "payable",
    direction_label: "We owe",
    kind: "trade",
    kind_label: "Trade credit",
    status: "open",
    party: { type: "counterparty", id: 7, name: "Grand Pharm" },
    currency: "UZS",
    amount: "5000000.00",
    paid: "0.00",
    outstanding: "5000000.00",
    base_outstanding: "5000000.00",
    issued_on: "2026-10-20",
    due_on: "2026-11-01",
    days_overdue: 5,
    description: "Nakladnoy №1042",
    branch: null,
    responsible: null,
    is_opening: false,
    is_locked: false,
    source: null,
    masked: false,
    created_at: "2026-10-20T10:00:00+05:00",
    bucket: "overdue",
    bank_only: false,
    ...overrides,
  }) as PayableDebt;

describe("payables helpers", () => {
  it("warns before a goods receipt is paid from cash, a safe or someone's money, never from a bank", () => {
    const receipt = [payable(1, { bank_only: true }), payable(2)];
    expect(bankTransferWarning(receipt, { kind: "cash" })).toBe(true);
    expect(bankTransferWarning(receipt, { kind: "safe" })).toBe(true);
    expect(bankTransferWarning(receipt, { kind: "employee" })).toBe(true);
    expect(bankTransferWarning(receipt, { kind: "owner" })).toBe(true);
    expect(bankTransferWarning(receipt, { kind: "bank" })).toBe(false);
    expect(bankTransferWarning(receipt, { kind: "card" })).toBe(false);
    // Rent from the cash desk is fine.
    expect(bankTransferWarning([payable(3)], { kind: "cash" })).toBe(false);
    expect(bankTransferWarning(receipt, null)).toBe(false);
  });

  it("adds payables up per bucket in the base currency", () => {
    const totals = bucketTotals([
      payable(1, { bucket: "overdue", base_outstanding: "1000.00" }),
      payable(2, { bucket: "week", base_outstanding: "250.50" }),
      payable(3, { bucket: "week", base_outstanding: "249.50" }),
      payable(4, { bucket: "later", base_outstanding: "12168.15", currency: "USD", outstanding: "1.00" }),
    ]);
    expect(totals).toEqual({ overdue: "1000.00", week: "500.00", later: "12168.15", all: "13668.15" });
  });

  it("accepts a payment above zero and up to what is left", () => {
    expect(validPayment("100", "100.00")).toBe(true);
    expect(validPayment("100.01", "100.00")).toBe(false);
    expect(validPayment("0", "100.00")).toBe(false);
    expect(validPayment(null, "100.00")).toBe(false);
    expect(validPayment("", "100.00")).toBe(false);
  });
});

// ─── Endpoints ─────────────────────────────────────────────────────────────────

describe("planning endpoints", () => {
  it("send the bodies the v6-i contract names", async () => {
    const calls = stub({
      "PUT budgets/": () => json({}),
      "POST budgets/copy/": () => json({}),
      "POST recurring/12/pay/": () => json({ rule: {}, transaction_id: 1 }),
      "POST recurring/12/skip/": () => json({}),
      "POST recurring/12/run-now/": () => json({ rule: {}, transaction_id: 2 }),
      "DELETE recurring/12/": () => json(null, 204),
      "POST recurring/templates/vat/apply/": () => json([], 201),
      "POST payables/pay/": () => json({ paid: [], warnings: [] }),
      "POST debts/44/credit/": () => json({}),
      "POST claims/5/approve/": () => json({}),
      "POST claims/5/reject/": () => json({}),
      "POST claims/5/pay/": () => json({}),
      "GET upcoming/": () => json({}),
      "GET reports/forecast/": () => json({}),
      "GET budgets/": () => json({}),
    });
    await financeApi.setBudgets(1, { month: "2026-11", rows: [{ category: 5, amount: "3000000" }, { category: 6, amount: null }] });
    await financeApi.copyBudgets(1, "2026-12");
    await financeApi.payRecurring(1, 12, { account: 3, amount: "12000000", paid_on: "2026-11-06", occurrence: "2026-11-05" });
    await financeApi.skipRecurring(1, 12, "2026-12-05");
    await financeApi.runRecurring(1, 12, null);
    await financeApi.stopRecurring(1, 12);
    await financeApi.applyTaxTemplate(1, "vat");
    await financeApi.payPayables(1, { account: 5, paid_on: "2026-11-06", debts: [{ id: 1, amount: "5000000" }] });
    await financeApi.creditDebt(1, 44, { amount: "200000", reason: "Return", credited_on: "2026-11-06" });
    await financeApi.approveClaim(1, 5);
    await financeApi.rejectClaim(1, 5, "No receipt");
    await financeApi.payClaim(1, 5, { account: 3, paid_on: "2026-11-06" });
    await financeApi.upcoming(1, 60);
    await financeApi.forecast(1, 90);
    await financeApi.budgets(1, "2026-11");
    const by = (method: string, path: string) => calls.find((call) => call.method === method && call.url.replace(PREFIX, "").split("?")[0] === path);
    expect(by("PUT", "budgets/")?.body).toEqual({ month: "2026-11", rows: [{ category: 5, amount: "3000000" }, { category: 6, amount: null }] });
    expect(by("POST", "budgets/copy/")?.body).toEqual({ month: "2026-12" });
    // The occurrence the person saw goes along, so a second press never settles the next one.
    expect(by("POST", "recurring/12/pay/")?.body).toEqual({ account: 3, amount: "12000000", paid_on: "2026-11-06", occurrence: "2026-11-05" });
    expect(by("POST", "recurring/12/skip/")?.body).toEqual({ occurrence: "2026-12-05" });
    expect(by("POST", "recurring/12/run-now/")?.body).toEqual({});
    expect(by("DELETE", "recurring/12/")).toBeTruthy();
    expect(by("POST", "recurring/templates/vat/apply/")?.body).toEqual({});
    expect(by("POST", "payables/pay/")?.body).toEqual({ account: 5, paid_on: "2026-11-06", debts: [{ id: 1, amount: "5000000" }] });
    expect(by("POST", "debts/44/credit/")?.body).toEqual({ amount: "200000", reason: "Return", credited_on: "2026-11-06" });
    expect(by("POST", "claims/5/reject/")?.body).toEqual({ reason: "No receipt" });
    expect(by("POST", "claims/5/pay/")?.body).toEqual({ account: 3, paid_on: "2026-11-06" });
    expect(by("GET", "upcoming/")?.url).toContain("days=60");
    expect(by("GET", "reports/forecast/")?.url).toContain("days=90");
    expect(by("GET", "budgets/")?.url).toContain("month=2026-11");
  });
});

// ─── Registration ──────────────────────────────────────────────────────────────

describe("planning in the module", () => {
  it("adds the five pages to the finance menu, the claims with their own badge", () => {
    const keys = (module.nav ?? []).map((entry) => entry.key);
    for (const key of ["payables", "claims", "calendar", "recurring", "budgets"]) expect(keys).toContain(key);
    const claims = module.nav?.find((entry) => entry.key === "claims");
    expect(claims?.perm).toEqual(["finance.approve", "finance.view"]);
    expect(claims?.badge?.({ counters: { "finance.claims": 3 }, versions: {} })).toBe(3);
    expect(module.badge?.({ counters: { "finance.overdue": 2, "finance.claims": 3 }, versions: {} })).toBe(2);
    expect(module.deepLinks?.recurring?.("12")).toBe("finance/recurring?rule=12");
    expect(module.deepLinks?.claims?.("")).toBe("finance/claims");
  });

  it("offers Budgets and Pay distributors in the palette, paying only to someone who sees the page", () => {
    const ctx = (perms: Perm[]) => ({ companyId: 1, company: company(), router: {} as never, t: (key: string) => key, can: (perm?: unknown) => perms.some((p) => (Array.isArray(perm) ? perm.includes(p) : perm === p)), go: () => {} });
    const ids = (perms: Perm[]) => (module.commands?.(ctx(perms) as never) ?? []).map((command) => command.id);
    expect(ids(["finance.view", "finance.record"])).toEqual(expect.arrayContaining(["finance.budgets", "finance.pay-distributors", "finance.upcoming", "finance.claims"]));
    expect(ids(["finance.record"])).not.toContain("finance.pay-distributors");
  });
});

// ─── Pages and dialogs ──────────────────────────────────────────────────────────

function as(permissions: Perm[]): void {
  useSessionStore().me = me([company({ is_owner: false, permissions })]);
}

const budgetMonth = () => ({
  month: "2026-11",
  currency: "UZS",
  days_left: 24,
  days_in_month: 30,
  rows: [row(1, "Ijara", "3000000.00", "2460000.00"), row(2, "Ijara › Chilonzor", null, "500000.00", 1), row(3, "Kommunal", null, "0.00")],
  totals: { budget: "3000000.00", actual: "2460000.00" },
});

describe("BudgetsPage", () => {
  it("shows subcategories under their parent, colours the bar by status and saves only the typed budget", async () => {
    const calls = stub({
      "GET budgets/": () => json(budgetMonth()),
      "PUT budgets/": (call) => json({ ...budgetMonth(), rows: budgetMonth().rows.map((r) => (r.category.id === 3 ? { ...r, budget: "1000000.00", share: "0.00", status: "ok" } : r)), totals: { budget: "4000000.00", actual: "2460000.00" }, month: (call.body as { month: string }).month }),
    });
    const app = await testApp("/c/1/finance/budgets?month=2026-11");
    const BudgetsPage = (await import("../pages/BudgetsPage.vue")).default;
    mountWithProviders(BudgetsPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    const ids = [...document.querySelectorAll("[data-budgets] tbody [data-category]")].map((el) => el.getAttribute("data-category"));
    expect(ids).toEqual(["1", "2", "3"]);
    expect(document.querySelector('[data-category="2"] td div')?.className).toContain("pl-6");
    expect(document.querySelector('[data-category="1"] [data-status]')?.getAttribute("data-status")).toBe("warning");

    const input = document.querySelector<HTMLInputElement>(`input[aria-label="${t("finance.budgets.budgetFor", { name: "Kommunal" })}"]`)!;
    input.value = "1000000";
    input.dispatchEvent(new Event("input"));
    await flushPromises();
    document.querySelector<HTMLButtonElement>("[data-save]")!.click();
    await flushPromises();
    const put = calls.find((call) => call.method === "PUT");
    expect(put?.body).toMatchObject({ month: "2026-11" });
    const sent = (put?.body as { rows: Array<{ category: number; amount: string }> }).rows;
    expect(sent).toHaveLength(1);
    expect(sent[0]!.category).toBe(3);
    expect(dec(sent[0]!.amount).eq(1000000)).toBe(true);
    expect(toasts.at(-1)?.title).toBe(en["finance.budgets.saved"]);
  });

  it("shows budgets read-only to someone who may only look", async () => {
    stub({ "GET budgets/": () => json(budgetMonth()) });
    const app = await testApp("/c/1/finance/budgets?month=2026-11");
    as(["finance.view"]);
    const BudgetsPage = (await import("../pages/BudgetsPage.vue")).default;
    mountWithProviders(BudgetsPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    expect(document.querySelector("[data-budgets] input")).toBeNull();
    expect(document.querySelector("[data-copy]")).toBeNull();
  });
});

describe("PayPayablesDialog", () => {
  it("warns about a goods receipt paid from the cash desk, and pays every picked debt in one call", async () => {
    const calls = stub({
      "GET options/": () => json(options()),
      "POST payables/pay/": () => json({ paid: [{ debt_id: 1, transaction_id: 91 }, { debt_id: 2, transaction_id: 92 }], warnings: [] }),
    });
    const app = await testApp("/c/1/finance/payables");
    const PayPayablesDialog = (await import("../components/PayPayablesDialog.vue")).default;
    const picks = [
      { debt: payable(1, { bank_only: true }), amount: "5000000.00" },
      { debt: payable(2, { party: { type: "counterparty", id: 8, name: "Oqtosh Med" } }), amount: "1200000" },
    ];
    mountWithProviders(PayPayablesDialog, { plugins: app.plugins, props: { open: true, picks } });
    await flushPromises();
    await flushPromises();
    // With a goods receipt among them, the bank account comes first and nothing warns.
    expect(document.querySelector('[role=radio][aria-checked="true"]')?.textContent).toContain("Asosiy bank hisobi");
    expect(document.querySelector("[data-bank-warning]")).toBeNull();
    expect(document.querySelector("[data-total]")?.textContent?.replace(/\D/g, "")).toContain("6200000");
    // The cash desk warns, and the button says so.
    [...document.querySelectorAll<HTMLButtonElement>("[role=radio]")].find((el) => el.textContent?.includes("Kassa"))!.click();
    await flushPromises();
    expect(document.querySelector("[data-bank-warning]")).not.toBeNull();
    expect(document.querySelector("[data-confirm-pay]")?.textContent).toContain(en["finance.payables.payAnyway"]);
    document.querySelector<HTMLButtonElement>("[data-confirm-pay]")!.click();
    await flushPromises();
    expect(calls.find((call) => call.method === "POST")?.body).toEqual({
      account: 3,
      paid_on: "2026-11-06",
      debts: [
        { id: 1, amount: "5000000.00" },
        { id: 2, amount: "1200000" },
      ],
    });
    expect(toasts.at(-1)?.title).toBe("2 debts paid");
  });
});

describe("PayablesPage", () => {
  const payables = () => ({
    today: "2026-11-06",
    currency: "UZS",
    groups: [
      {
        counterparty: { id: 7, name: "Grand Pharm" },
        total: "6200000.00",
        overdue: "5000000.00",
        debts: [payable(1, { bank_only: true }), payable(2, { bucket: "week", outstanding: "1200000.00", base_outstanding: "1200000.00", days_overdue: 0, due_on: "2026-11-09", description: "Nakladnoy №1077" })],
      },
      { counterparty: { id: 8, name: "Oqtosh Med" }, total: "800000.00", overdue: "0.00", debts: [payable(3, { bucket: "later", outstanding: "800000.00", base_outstanding: "800000.00", days_overdue: 0, due_on: "2026-12-01", party: { type: "counterparty", id: 8, name: "Oqtosh Med" } })] },
    ],
    totals: { overdue: "5000000.00", week: "1200000.00", later: "800000.00", all: "7000000.00" },
  });

  it("ticks the debt a calendar link names, a whole distributor at once, filters by bucket and pays the picked ones", async () => {
    stub({ "GET payables/": () => json(payables()), "GET options/": () => json(options()) });
    const app = await testApp("/c/1/finance/payables?select=2");
    const PayablesPage = (await import("../pages/PayablesPage.vue")).default;
    mountWithProviders(PayablesPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    const bar = () => document.querySelector('[role="toolbar"]')?.textContent ?? "";
    expect(bar()).toContain("1 selected");
    // The amount to pay is what is left, until someone types another.
    expect(document.querySelector<HTMLInputElement>('[data-debt="2"] input')?.value).toBe("1,200,000");
    expect(app.router.currentRoute.value.query.select).toBeUndefined();

    document.querySelector<HTMLButtonElement>('[data-group="8"] header [role="checkbox"]')!.click();
    await flushPromises();
    expect(bar()).toContain("2 selected");
    expect(document.querySelector('[data-debt="1"]')?.textContent).toContain(en["finance.payables.bankOnly"]);

    document.querySelector<HTMLButtonElement>("[data-pay-selected]")!.click();
    await flushPromises();
    await flushPromises();
    expect(document.querySelector("[data-pay-payables] [data-total]")?.textContent?.replace(/\D/g, "")).toContain("2000000");
  });

  it("opens a payable that isn't a distributor's in the debt drawer", async () => {
    stub({ "GET payables/": () => json(payables()), "GET debts/99/": () => json({ detail: "Not found." }, 404) });
    const app = await testApp("/c/1/finance/payables?select=99");
    const PayablesPage = (await import("../pages/PayablesPage.vue")).default;
    mountWithProviders(PayablesPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    expect(app.router.currentRoute.value.query).toMatchObject({ debt: "99" });
    expect(app.router.currentRoute.value.query.select).toBeUndefined();
  });
});

describe("PreferencesPanel tax regime", () => {
  const settings = (overrides: Record<string, unknown> = {}) => ({
    locked_until: null,
    rate_source: "cbu",
    approval_threshold: null,
    receipt_required_over: null,
    large_expense_alert: null,
    reimburse_via: "payroll",
    base_currency: "UZS",
    can_reopen: true,
    tax_regime: "turnover",
    vat_percent: "0.00",
    turnover_threshold: 12000,
    base_value: "412000.00",
    tax_regime_set: true,
    payroll_on: false,
    ...overrides,
  });

  it("greys out payback with the payroll while payroll is off, and saves only what changed with the regime's rate", async () => {
    const calls = stub({
      "GET settings/": () => json(settings()),
      "GET tax-summary/": () => json({ regime: "turnover", vat_percent: "0.00", year: 2026, currency: "UZS", turnover: "1820000000.00", threshold: "4944000000.00", threshold_values: 12000, base_value: "412000.00", share: "0.37", over: false }),
      "PATCH settings/": () => json(settings({ tax_regime: "vat", vat_percent: "12.00" })),
    });
    const app = await testApp("/c/1/finance/settings/preferences");
    const PreferencesPanel = (await import("../components/settings/PreferencesPanel.vue")).default;
    mountWithProviders(PreferencesPanel, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    const radios = [...document.querySelectorAll<HTMLButtonElement>('[role="radio"]')];
    const payroll = radios.find((el) => el.textContent?.includes(en["finance.prefs.viaPayroll"]));
    expect(payroll?.hasAttribute("disabled") || payroll?.getAttribute("aria-disabled") === "true" || payroll?.hasAttribute("data-disabled")).toBe(true);
    expect(document.body.textContent).toContain(en["finance.prefs.viaPayrollOff"]);
    // Payroll off reads as "cash" already: nothing to save until something changes.
    expect(document.body.textContent).not.toContain("You have unsaved changes");
    expect(document.querySelector("[data-turnover]")).not.toBeNull();

    radios.find((el) => el.textContent?.includes(en["finance.taxRegime.vat"]) && !el.textContent?.includes(en["finance.taxRegime.vat_simplified"]))!.click();
    await flushPromises();
    [...document.querySelectorAll<HTMLButtonElement>("button")].find((el) => el.textContent?.trim() === "Save")!.click();
    await flushPromises();
    expect(calls.find((call) => call.method === "PATCH")?.body).toEqual({ tax_regime: "vat", vat_percent: "12.00" });
  });

  it("asks to confirm a regime nobody confirmed yet, and confirms the one on screen", async () => {
    const calls = stub({
      "GET settings/": () => json(settings({ tax_regime_set: false })),
      "GET tax-summary/": () => json({ regime: "turnover", vat_percent: "0.00", year: 2026, currency: "UZS", turnover: "0.00", threshold: "0.00", threshold_values: 0, base_value: "0.00", share: null, over: false }),
      "PATCH settings/": () => json(settings()),
    });
    const app = await testApp("/c/1/finance/settings/preferences");
    const PreferencesPanel = (await import("../components/settings/PreferencesPanel.vue")).default;
    mountWithProviders(PreferencesPanel, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    document.querySelector<HTMLButtonElement>("[data-confirm-regime]")!.click();
    await flushPromises();
    expect(calls.find((call) => call.method === "PATCH")?.body).toEqual({ tax_regime: "turnover", vat_percent: "0.00" });
  });
});

describe("CalendarPage", () => {
  const forecast = {
    today: "2026-11-06",
    days: 30,
    currency: "UZS",
    start: "54000000.00",
    points: [
      { date: "2026-11-06", balance: "54000000.00", in: "0.00", out: "0.00" },
      { date: "2026-11-25", balance: "-3200000.00", in: "0.00", out: "57200000.00" },
    ],
    low: { date: "2026-11-25", balance: "-3200000.00" },
    below_zero_on: "2026-11-25",
    end: "-1000000.00",
    basis: { daily_in: "4000000.00", daily_out: "3100000.00", days_observed: 56 },
    events: [],
  };
  const rule = {
    id: 12,
    name: "Ijara",
    kind: "expense",
    mode: "bill",
    frequency: "monthly",
    interval: 1,
    day: 25,
    on_holiday: "before",
    category: { id: 4, name: "Ijara", kind: "expense", color: "", parent_id: null },
    counterparty: { id: 9, name: "Ijara beruvchi" },
    account: { id: 5, name: "Asosiy bank hisobi", kind: "bank", currency: "UZS" },
    branch: null,
    amount: "12000000.00",
    currency: "UZS",
    amount_varies: false,
    starts_on: "2026-01-25",
    ends_on: null,
    next_due_on: "2026-11-25",
    overdue: false,
    remind_days_before: 3,
    payer: null,
    template_key: "",
    is_tax: false,
    is_active: true,
    last_done_on: "2026-10-25",
    upcoming: ["2026-11-25", "2026-12-25", "2027-01-25"],
    created_at: "2026-01-10T10:00:00+05:00",
  };

  it("says when cash goes below zero and pays a bill from the list in place", async () => {
    const calls = stub({
      "GET reports/forecast/": () => json(forecast),
      "GET upcoming/": () =>
        json({
          today: "2026-11-06",
          days: 30,
          currency: "UZS",
          items: [item({ key: "rule:12:2026-11-25", rule_id: 12, date: "2026-11-25" }), item({ key: "debt:44", kind: "payable", rule_id: null, debt_id: 44, title: "Grand Pharm", date: "2026-11-02", overdue: true })],
          totals: { out: "17000000.00", in: "0.00", overdue_out: "12000000.00", overdue_in: "0.00" },
        }),
      "GET recurring/": () => json([rule]),
      "GET options/": () => json(options()),
      "POST recurring/12/pay/": () => json({ rule: { ...rule, next_due_on: "2026-12-25" }, transaction_id: 301 }),
    });
    const app = await testApp("/c/1/finance/calendar");
    const CalendarPage = (await import("../pages/CalendarPage.vue")).default;
    mountWithProviders(CalendarPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    expect(document.querySelector('[data-headline="below"]')?.textContent).toContain("Cash drops below zero on");
    // Overdue first, then the days.
    expect([...document.querySelectorAll("[data-group]")].map((el) => el.getAttribute("data-group"))).toEqual(["overdue", "2026-11-25"]);
    expect(document.querySelector('[data-item="debt:44"] a')?.getAttribute("href")).toBe("/c/1/finance/payables?select=44");
    document.querySelector<HTMLButtonElement>('[data-item="rule:12:2026-11-25"] button')!.click();
    await flushPromises();
    await flushPromises();
    expect(document.querySelector("[data-pay-rule]")).not.toBeNull();
    document.querySelector<HTMLButtonElement>("[data-confirm-pay]")!.click();
    await flushPromises();
    expect(calls.find((call) => call.method === "POST")?.body).toMatchObject({ account: 5, amount: "12000000.00", paid_on: "2026-11-06" });
    expect(toasts.at(-1)?.title).toBe("Paid: Ijara");
  });
});

describe("ClaimsPage", () => {
  const claim = (overrides: Record<string, unknown> = {}) => ({
    id: 5,
    member: { id: 21, name: "Madina Yusupova", photo_url: null },
    amount: "450000.00",
    currency: "UZS",
    category: { id: 4, name: "Xo‘jalik mollari", kind: "expense", color: "", parent_id: null },
    spent_on: "2026-11-05",
    description: "Tozalash vositalari",
    paid_from: "own_money",
    status: "submitted",
    status_label: "Waiting",
    branch: { id: 1, name: "Chilonzor" },
    receipts: [{ id: 1, url: "/files/r1.jpg", thumb_url: "/files/r1-thumb.jpg", content_type: "image/jpeg", is_image: true }],
    created_at: "2026-11-05T12:00:00+05:00",
    decided_by: null,
    decided_at: null,
    reject_reason: "",
    reimburse_via: "cash",
    transaction_id: null,
    debt_id: null,
    can_decide: true,
    can_pay: false,
    can_cancel: false,
    ...overrides,
  });

  it("lists the waiting claims with their receipt and approves one", async () => {
    const calls = stub({
      "GET claims/": () => json({ count: 1, next: null, previous: null, results: [claim()] }),
      "POST claims/5/approve/": () => json(claim({ status: "approved", can_decide: false, can_pay: true })),
    });
    const app = await testApp("/c/1/finance/claims");
    const ClaimsPage = (await import("../pages/ClaimsPage.vue")).default;
    mountWithProviders(ClaimsPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    expect(calls.find((call) => call.method === "GET")?.url).toContain("status=submitted");
    const card = document.querySelector('[data-claim="5"]')!;
    expect(card.textContent).toContain("Madina Yusupova");
    expect(card.textContent).toContain(en["finance.claims.from.own_cash"]);
    expect(card.querySelector("[data-receipt] img")?.getAttribute("src")).toBe("/files/r1-thumb.jpg");
    [...card.querySelectorAll<HTMLButtonElement>("button")].find((el) => el.textContent?.includes("Approve"))!.click();
    await flushPromises();
    expect(calls.some((call) => call.method === "POST" && call.url.endsWith("claims/5/approve/"))).toBe(true);
    expect(toasts.at(-1)?.title).toBe("Approved: Madina Yusupova");
  });
});
