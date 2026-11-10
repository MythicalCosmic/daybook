// v11: the owner's money. The pure helpers behind the hero bar and the partners' dialogs, the page
// (the safe amount with its reasons, this month's draws), taking money out above the safe amount
// (a warning that needs a tick), and setting the partners' shares (exactly 100 %).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { toasts } from "@/components/useToast";
import { mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import en from "../i18n/en.json";
import { cashSplit, lastQuarter, ownerMoneyApi, sharesTotal, splitByShares, type OwnerMoney, type Partners } from "../ownerMoney";

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

function summary(overrides: Partial<OwnerMoney> = {}): OwnerMoney {
  return {
    today: "2026-11-10",
    currency: "UZS",
    horizon_days: 30,
    until: "2026-12-10",
    cash: "540907485.00",
    personal: "0.00",
    complete: true,
    due: "369030200.00",
    reasons: [
      { key: "payable:12", kind: "payable", title: "Ko‘kterak Farm Distribyutor", subtitle: "3 payments", date: "2026-11-08", amount: "88142200.00", count: 3, overdue: true, estimate: false, url: "/c/1/finance/payables" },
      { key: "payroll:2026-12-05", kind: "payroll", title: "Payroll", subtitle: "Pay day", date: "2026-12-05", amount: "97064000.00", count: 1, overdue: false, estimate: true, url: "/c/1/payroll" },
      { key: "instalment:4", kind: "loan", title: "Bank", subtitle: "Aylanma kredit", date: "2026-12-05", amount: "6700000.00", count: 1, overdue: false, estimate: false, url: "/c/1/finance/debts?debt=9" },
      { key: "rule:3:2026-11-15", kind: "tax", title: "QQS", subtitle: "", date: "2026-11-20", amount: null, count: 1, overdue: false, estimate: true, url: "/c/1/finance/recurring?rule=3" },
    ],
    unknown: 1,
    buffer: { amount: "122265800.00", auto: true, fixed_costs: "122265800.00" },
    planned: "14500000.00",
    purchases: { kept: [{ id: 1, title: "Muzlatgich", amount: "14500000.00", due_on: "2026-11-28", branch: null, done: false }], later: [] },
    safe: "35111485.00",
    short: "0.00",
    month: {
      from: "2026-11-01",
      to: "2026-11-10",
      drawn: "15500000.00",
      put_in: "0.00",
      net: "-15500000.00",
      count: 2,
      rows: [
        { id: 91, occurred_on: "2026-11-07", direction: "out", amount: "3500000.00", currency: "UZS", base_amount: "3500000.00", account: { id: 5, name: "Asosiy bank hisobi", kind: "bank" }, description: "Oilaviy xarajatlar uchun", person: null, dividend: false, created_by: "Dilnoza Karimova" },
      ],
    },
    suggestion: {
      today: "2026-11-10",
      currency: "UZS",
      days: 90,
      monthly: "150100000.00",
      dates: ["2026-12-01", "2027-01-01", "2027-02-01"],
      buffer: "122265800.00",
      low: { date: "2027-02-05", balance: "122320105.08" },
      below_buffer_on: null,
      profit_average: "-16000000.00",
      above_profit: true,
    },
    history: [
      { month: "2026-10-01", profit: "-72657528.92", drawn: "22400000.00", put_in: "0.00" },
      { month: "2026-11-01", profit: "-1548529.00", drawn: "15500000.00", put_in: "0.00" },
    ],
    accounts: [
      { id: 5, name: "Asosiy bank hisobi", kind: "bank", currency: "UZS", balance: "400000000.00", branch_id: null },
      { id: 3, name: "Chilonzor, Kassa", kind: "cash", currency: "UZS", balance: "2300000.00", branch_id: 1 },
    ],
    settings: { cash_buffer: null, draw_horizon_days: 30 },
    partners: 2,
    is_owner: true,
    ...overrides,
  };
}

describe("owner money helpers", () => {
  it("splits the cash into payments, buffer, planned purchases and the safe part", () => {
    const parts = cashSplit({ cash: "100", due: "50", buffer: { amount: "20", auto: true, fixed_costs: "20" }, planned: "10", safe: "20" });
    expect(parts.map((part) => [part.key, part.share])).toEqual([
      ["due", 50],
      ["buffer", 20],
      ["planned", 10],
      ["safe", 20],
    ]);
    // Short of money: the needs fill the bar, nothing is safe.
    const short = cashSplit({ cash: "60", due: "50", buffer: { amount: "30", auto: true, fixed_costs: "30" }, planned: "0", safe: "0" });
    expect(short.reduce((sum, part) => sum + part.share, 0)).toBeCloseTo(100, 5);
    expect(short.find((part) => part.key === "safe")?.share).toBe(0);
    expect(cashSplit({ cash: "0", due: "0", buffer: { amount: "0", auto: true, fixed_costs: "0" }, planned: "0", safe: "0" }).every((part) => part.share === 0)).toBe(true);
  });

  it("adds the shares to the hundredth and splits a dividend as the server does", () => {
    expect(sharesTotal([{ share: 60 }, { share: 40 }])).toEqual({ total: 100, exact: true });
    expect(sharesTotal([{ share: 33.33 }, { share: 33.33 }, { share: 33.33 }])).toEqual({ total: 99.99, exact: false });
    expect(sharesTotal([{ share: null }, { share: 100 }]).exact).toBe(true);
    expect(splitByShares(10000000.01, [60, 40])).toEqual([6000000.01, 4000000]);
    expect(splitByShares(100, [33.33, 33.33, 33.34])).toEqual([33.33, 33.33, 33.34]);
    expect(splitByShares(5, [])).toEqual([]);
  });

  it("knows last quarter across a year", () => {
    expect(lastQuarter("2026-11-10")).toEqual({ from: "2026-07-01", to: "2026-09-30" });
    expect(lastQuarter("2026-02-03")).toEqual({ from: "2025-10-01", to: "2025-12-31" });
    expect(lastQuarter("2026-05-31")).toEqual({ from: "2026-01-01", to: "2026-03-31" });
  });

  it("sends the endpoints' bodies", async () => {
    const calls = stub({
      "POST owner-money/take/": () => json({ id: 1, occurred_on: "2026-11-10", amount: "1000.00", account: 5, safe: "0.00" }, 201),
      "PATCH owner-money/settings/": () => json({ cash_buffer: null, draw_horizon_days: 45 }),
      "PUT partners/": () => json({ current: [], history: [], since: null, people: [] }),
      "POST dividends/7/pay/": () => json({}),
      "POST dividends/7/lines/3/undo/": () => json({}),
    });
    await ownerMoneyApi.take(1, { account: 5, amount: "1000", confirmed: true });
    await ownerMoneyApi.settings(1, { cash_buffer: null, draw_horizon_days: 45 });
    await ownerMoneyApi.setPartners(1, { effective_on: "2026-01-01", partners: [{ member: 11, share: "60" }, { name: "Rustam Qodirov", share: "40" }] });
    await ownerMoneyApi.payDividend(1, 7, { account: 5, paid_on: "2026-11-10", lines: [3, 4] });
    await ownerMoneyApi.undoLine(1, 7, 3, "Xato");
    expect(calls.map((call) => `${call.method} ${call.url.replace(PREFIX, "")}`)).toEqual([
      "POST owner-money/take/",
      "PATCH owner-money/settings/",
      "PUT partners/",
      "POST dividends/7/pay/",
      "POST dividends/7/lines/3/undo/",
    ]);
    expect(calls[0]!.body).toEqual({ account: 5, amount: "1000", confirmed: true });
    expect(calls[2]!.body).toEqual({ effective_on: "2026-01-01", partners: [{ member: 11, share: "60" }, { name: "Rustam Qodirov", share: "40" }] });
    expect(calls[4]!.body).toEqual({ reason: "Xato" });
  });
});

describe("MyMoneyPage", () => {
  it("shows the safe amount with its reasons, the buffer and this month's draws", async () => {
    stub({ "GET owner-money/": () => json(summary()) });
    const app = await testApp("/c/1/finance/my-money");
    const Page = (await import("../pages/MyMoneyPage.vue")).default;
    mountWithProviders(Page, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();

    expect(document.querySelector("[data-safe-amount]")?.textContent?.replace(/\D/g, "")).toBe("35111485");
    const reasons = [...document.querySelectorAll("[data-reason]")].map((el) => el.getAttribute("data-reason"));
    expect(reasons).toEqual(["payable", "payroll", "loan"]);
    // An estimate is marked; the one with no amount is listed apart, not counted.
    expect(document.querySelector('[data-reason="payroll"]')?.textContent).toContain(en["finance.myMoney.estimate"]);
    expect(document.querySelector("[data-unknown]")?.textContent).toContain("QQS");
    expect(document.querySelector("[data-month]")?.textContent).toContain("Oilaviy xarajatlar uchun");
    // The monthly plan says when it is more than the business earns.
    expect(document.querySelector("[data-above-profit]")).not.toBeNull();
  });

  it("asks for a tick before taking more than is safe, then books it", async () => {
    const calls = stub({
      "GET owner-money/": () => json(summary()),
      "POST owner-money/take/": () => json({ id: 1, occurred_on: "2026-11-10", amount: "50000000.00", account: 5, safe: "0.00" }, 201),
    });
    const app = await testApp("/c/1/finance/my-money");
    const Page = (await import("../pages/MyMoneyPage.vue")).default;
    mountWithProviders(Page, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();

    document.querySelector<HTMLButtonElement>("[data-take]")!.click();
    await flushPromises();
    // The biggest business account is picked.
    expect(document.querySelector('[role=radio][aria-checked="true"]')?.textContent).toContain("Asosiy bank hisobi");
    const input = document.querySelector<HTMLInputElement>("input[data-amount]")!;
    input.value = "50000000";
    input.dispatchEvent(new Event("input"));
    await flushPromises();
    expect(document.querySelector("[data-over]")).not.toBeNull();
    const save = document.querySelector<HTMLButtonElement>("[data-save]")!;
    expect(save.disabled).toBe(true);
    expect(save.textContent).toContain(en["finance.myMoney.takeAnyway"]);

    document.querySelector<HTMLElement>("[data-confirm] button, [data-confirm] [role=checkbox]")!.click();
    await flushPromises();
    expect(save.disabled).toBe(false);
    save.click();
    await flushPromises();
    await flushPromises();
    const take = calls.find((call) => call.method === "POST");
    expect(take?.body).toMatchObject({ account: 5, amount: "50000000.00", confirmed: true, occurred_on: "2026-11-10" });
  });

  it("sets the partners only when the shares make exactly 100 %", async () => {
    const partners: Partners = { current: [], history: [], since: null, people: [{ id: 11, name: "Dilnoza Karimova" }] };
    const calls = stub({
      "GET owner-money/": () => json(summary({ partners: 0 })),
      "GET partners/": () => json(partners),
      "GET partners/profit-share/": () => json({ from: "2026-01-01", to: "2026-11-10", currency: "UZS", profit: "0.00", partners: [], unassigned_share: "100.00" }),
      "GET dividends/": () => json([]),
      "PUT partners/": () => json(partners),
    });
    const app = await testApp("/c/1/finance/my-money?tab=partners");
    const Page = (await import("../pages/MyMoneyPage.vue")).default;
    mountWithProviders(Page, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();

    document.querySelector<HTMLButtonElement>("[data-add-partners]")!.click();
    await flushPromises();
    // One row of 100 % to start with.
    expect(document.querySelector("[data-total]")?.className).toContain("success");
    document.querySelector<HTMLButtonElement>("[data-add-name]")!.click();
    await flushPromises();
    const type = async (input: HTMLInputElement, value: string) => {
      input.value = value;
      input.dispatchEvent(new Event("input"));
      await flushPromises();
    };
    const shares = [...document.querySelectorAll<HTMLInputElement>("[data-partner-rows] [role=spinbutton]")];
    expect(shares).toHaveLength(2);
    await type(shares[0]!, "60");
    await type(shares[1]!, "30");
    expect(document.querySelector("[data-total]")?.className).toContain("warning");
    expect(document.querySelector<HTMLButtonElement>("[data-save]")?.disabled).toBe(true);
    await type(shares[1]!, "40");
    expect(document.querySelector("[data-total]")?.className).toContain("success");
    await type(document.querySelector<HTMLInputElement>('[data-partner-rows] input[type="text"]:not([role])')!, "Rustam Qodirov");
    // The person of the first row isn't picked yet: nothing is sent.
    document.querySelector<HTMLButtonElement>("[data-save]")!.click();
    await flushPromises();
    expect(calls.some((call) => call.method === "PUT")).toBe(false);
    expect(document.querySelector("[data-error]")?.textContent).toContain(en["finance.partners.fillEveryRow"]);
  });
});
