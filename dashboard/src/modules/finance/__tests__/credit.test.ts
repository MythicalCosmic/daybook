// v12: loans (schedule, paying, early repayment) and the tax calendar (deadlines, marks, the
// turnover tax / VAT comparison), the supplier terms on a counterparty, and the module's menu.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { toasts } from "@/components/useToast";
import { mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import { deadlinesByMonth, deadlinesInOrder, principalGap, repaidShare, type Loan, type LoanLine, type TaxDeadline } from "../credit";
import en from "../i18n/en.json";
import ru from "../i18n/ru.json";
import uz from "../i18n/uz.json";
import module from "../index";
import type { Options } from "../types";

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
      const body = raw ? JSON.parse(String(raw)) : undefined;
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

const options = (): Options =>
  ({
    base_currency: "UZS",
    today: "2026-11-12",
    accounts: [
      { id: 3, name: "Kassa", kind: "cash", currency: "UZS", branch_id: 1 },
      { id: 5, name: "Asosiy bank hisobi", kind: "bank", currency: "UZS", branch_id: null },
    ],
    branches: [],
    members: [],
    locked_until: null,
  }) as unknown as Options;

const line = (id: number, extra: Partial<LoanLine> = {}): LoanLine => ({
  id,
  position: id,
  due_on: `2026-${String(10 + id).padStart(2, "0")}-05`,
  principal: "1000000.00",
  interest: "240000.00",
  payment: "1240000.00",
  principal_paid: "0.00",
  interest_paid: "0.00",
  rest: "1240000.00",
  balance: "11000000.00",
  status: "due",
  early: false,
  ...extra,
});

const loan = (extra: Partial<Loan> = {}): Loan => ({
  id: 4,
  debt_id: 40,
  direction: "payable",
  direction_label: "Loan taken",
  counterparty: { id: 9, name: "Hamkorbank" },
  branch: null,
  account: { id: 5, name: "Asosiy bank hisobi", kind: "bank", currency: "UZS" },
  description: "Aylanma mablag‘",
  currency: "UZS",
  status: "open",
  is_opening: false,
  issued_on: "2026-10-05",
  ends_on: "2027-10-05",
  annual_rate: "24.000",
  method: "equal_principal",
  method_label: "Equal principal, payments fall",
  basis: "monthly",
  term_months: 12,
  first_due_on: "2026-11-05",
  grace_months: 0,
  fee: "0.00",
  amount: "12000000.00",
  owed: "9000000.00",
  paid_principal: "3000000.00",
  interest_paid: "700000.00",
  interest_left: "860000.00",
  next: line(1, { status: "overdue" }),
  overdue_count: 1,
  overdue_amount: "1240000.00",
  payments_left: 9,
  payments: 12,
  ...extra,
});

const deadline = (key: string, due: string, extra: Partial<TaxDeadline> = {}): TaxDeadline => ({
  key: `${key}:${due.slice(0, 8)}01`,
  rule: key,
  tax: key,
  tax_name: "VAT (QQS)",
  name: "VAT return and payment",
  period: "month",
  period_start: `${due.slice(0, 8)}01`,
  period_end: `${due.slice(0, 8)}28`,
  period_label: "noyabr 2026",
  due_on: due,
  action: "file_pay",
  action_label: "File the return and pay",
  estimate: "6000000.00",
  basis: "VAT in sales less VAT in goods bought",
  booked: false,
  currency: "UZS",
  status: "due",
  done_on: null,
  mark_id: null,
  paid: null,
  transaction_id: null,
  debt_id: null,
  rule_id: null,
  rate: "12",
  law: "Tax Code arts. 259, 273",
  url: "https://lex.uz/ru/docs/4674893",
  confidence: "H",
  note: "",
  ...extra,
});

describe("credit helpers", () => {
  it("says how much of a loan is repaid", () => {
    expect(repaidShare({ amount: "12000000.00", owed: "9000000.00" })).toBe(25);
    expect(repaidShare({ amount: "0.00", owed: "0.00" })).toBe(0);
    expect(repaidShare({ amount: "100.00", owed: "-5.00" })).toBe(100);
  });

  it("puts late deadlines first, then the soonest, done ones last", () => {
    const rows = [deadline("vat", "2026-12-21"), deadline("profit", "2026-11-20", { status: "done" }), deadline("social_tax", "2026-10-15", { status: "overdue" }), deadline("income_tax", "2026-12-15")];
    expect(deadlinesInOrder(rows).map((row) => row.rule)).toEqual(["social_tax", "income_tax", "vat", "profit"]);
    expect(deadlinesByMonth(rows).map((group) => [group.month, group.rows.length])).toEqual([
      ["2026-10", 1],
      ["2026-11", 1],
      ["2026-12", 2],
    ]);
  });

  it("tells how far a typed schedule is from the loan", () => {
    expect(principalGap("1000.00", [{ due_on: "2026-12-01", principal: "400", interest: "5" }, { due_on: "2027-01-01", principal: "600", interest: "" }])).toBe("0.00");
    expect(principalGap("1000.00", [{ due_on: "2026-12-01", principal: "400", interest: "5" }])).toBe("600.00");
  });

  it("has every new key in all three languages, plurals in three forms", () => {
    const mine = Object.keys(en).filter((key) => /^finance\.(loans|taxes|parties\.terms|nav\.(loans|taxes)|cmd\.(loans|taxes|suppliersOverdue)|prefs\.(deadlines|loanRemind|taxRemind|remindHint|daysBefore|turnoverRate|owns))/.test(key));
    expect(mine.length).toBeGreaterThan(150);
    for (const key of mine) {
      const forms = [(en as Record<string, string>)[key], (uz as Record<string, string>)[key], (ru as Record<string, string>)[key]];
      expect(forms.every((text) => !!text), key).toBe(true);
      expect(new Set(forms.map((text) => text!.split(" | ").length)).size, key).toBe(1);
      expect((uz as Record<string, string>)[key]).not.toMatch(/['`]/);
    }
  });
});

describe("credit in the module", () => {
  it("adds Loans and the tax calendar to the finance menu, and links a loan's reminder to it", () => {
    const keys = (module.nav ?? []).map((entry) => entry.key);
    expect(keys).toEqual(expect.arrayContaining(["loans", "taxes"]));
    expect(module.deepLinks?.loan?.("7")).toBe("finance/loans/7");
    expect(module.deepLinks?.taxes?.("")).toBe("finance/taxes");
    const ctx = { companyId: 1, router: {} as never, t: (key: string) => key, can: () => true, go: vi.fn() };
    const commands = module.commands?.(ctx as never) ?? [];
    const overdue = commands.find((command) => command.id === "finance.suppliers-overdue");
    overdue?.run?.();
    expect(ctx.go).toHaveBeenCalledWith("finance/payables?bucket=overdue");
  });
});

describe("LoansPage", () => {
  it("shows each loan with what is owed, how much is repaid and a late payment", async () => {
    stub({
      "GET loans/": () => json({ currency: "UZS", owed: "9000000.00", owed_to_us: "0.00", due_30: "1240000.00", overdue: "1240000.00", loans: [loan(), loan({ id: 5, status: "paid", owed: "0.00", next: null, overdue_count: 0 })] }),
    });
    const app = await testApp("/c/1/finance/loans");
    const LoansPage = (await import("../pages/LoansPage.vue")).default;
    mountWithProviders(LoansPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    const card = document.querySelector('[data-loan="4"]');
    expect(card?.textContent).toContain("Hamkorbank");
    expect(card?.textContent).toContain("1 late");
    expect(card?.getAttribute("href")).toBe("/c/1/finance/loans/4");
    expect(document.querySelector('[data-loan="5"]')).toBeNull();
    expect(document.body.textContent).toContain("Repaid loan (1)");
  });
});

describe("LoanDetailPage", () => {
  const detail = () => ({
    loan: loan(),
    schedule: [line(1, { status: "overdue" }), line(2, { principal: "1000000.00", interest: "220000.00", payment: "1220000.00", rest: "1220000.00", balance: "10000000.00" })],
    payments: [],
    can_pay: true,
    can_edit_schedule: false,
    can_undo: true,
  });

  it("lists the schedule and pays the next payment split into principal and interest", async () => {
    const calls = stub({
      "GET loans/4/": () => json(detail()),
      "GET options/": () => json(options()),
      "POST loans/4/pay/": () => json(detail()),
    });
    const app = await testApp("/c/1/finance");
    // The page reads its loan from the route's :loanId.
    app.router.addRoute({ path: "/c/:companyId/finance/loans/:loanId", component: { render: () => null } });
    await app.router.push("/c/1/finance/loans/4");
    const LoanDetailPage = (await import("../pages/LoanDetailPage.vue")).default;
    mountWithProviders(LoanDetailPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    expect(document.querySelectorAll("[data-schedule] tbody tr")).toHaveLength(2);
    expect(document.querySelector('[data-line="1"]')?.textContent).toContain(en["finance.installment.overdue"]);
    expect(document.querySelector("[data-edit-schedule]")).toBeNull();
    document.querySelector<HTMLButtonElement>("[data-pay-line]")!.click();
    await flushPromises();
    await flushPromises();
    document.querySelector<HTMLButtonElement>("[data-pay-loan]")!.click();
    await flushPromises();
    const pay = calls.find((call) => call.method === "POST" && call.url.endsWith("loans/4/pay/"));
    expect(pay?.body).toMatchObject({ installment: 1, account: 5, principal: "1000000.00", interest: "240000.00", paid_on: "2026-11-12" });
  });
});

describe("TaxesPage", () => {
  const calendar = () => ({
    today: "2026-11-12",
    from: "2026-10-01",
    to: "2027-11-30",
    currency: "UZS",
    regime: "turnover",
    regime_label: "Turnover tax",
    profile: { payroll: true, property: false, land: false, big_income: false },
    remind_days: 5,
    warnings: ["Since 1 April 2025 a business that sells medicines can't pay turnover tax."],
    deadlines: [deadline("turnover", "2026-11-16", { tax_name: "Turnover tax", name: "Turnover tax return and payment", estimate: "2000000.00" }), deadline("social_tax", "2026-10-15", { status: "overdue", name: "Social tax return and payment" })],
    checked_on: "2026-11-12",
    sources: [{ label: "Tax Code", url: "https://lex.uz/ru/docs/4674893" }],
    disclaimer: "Check with your accountant.",
  });

  it("warns about the regime, shows the late deadline first and records a payment", async () => {
    const calls = stub({
      "GET taxes/": () => json(calendar()),
      "GET taxes/compare/": () => json({ detail: "x" }, 500),
      "GET options/": () => json(options()),
      "POST taxes/marks/": () => json({ id: 1 }, 201),
    });
    const app = await testApp("/c/1/finance/taxes");
    const TaxesPage = (await import("../pages/TaxesPage.vue")).default;
    mountWithProviders(TaxesPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    expect(document.querySelector("[data-regime-warning]")?.textContent).toContain("medicines");
    const rows = [...document.querySelectorAll("[data-deadline]")].map((el) => el.getAttribute("data-deadline"));
    expect(rows[0]).toBe("social_tax:2026-10-01");
    expect(document.querySelector("[data-tax-sources]")?.textContent).toContain("Check with your accountant.");
    document.querySelector<HTMLButtonElement>('[data-mark="turnover:2026-11-01"]')!.click();
    await flushPromises();
    await flushPromises();
    document.querySelector<HTMLButtonElement>("[data-save-mark]")!.click();
    await flushPromises();
    const mark = calls.find((call) => call.method === "POST" && call.url.endsWith("taxes/marks/"));
    expect(mark?.body).toMatchObject({ rule: "turnover", period_start: "2026-11-01", account: 5, amount: "2000000.00", done_on: "2026-11-12" });
  });
});
