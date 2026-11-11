// v12: reports for banks and investors. The period choices of the dialog, the balance sheet tab
// (both sides, the gaps in words, the balance note), what the business is worth (both methods and
// changing the multiples), and preparing the PDF (the request, the progress, the download).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mergeModuleMessages } from "@/i18n";
import { useSessionStore } from "@/stores/session";
import { company, json, manager, me } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import en from "../i18n/en.json";
import { periodChoices, type BalanceSheet, type StatementPack, type Valuation } from "../statements";

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
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

function sheet(overrides: Partial<BalanceSheet> = {}): BalanceSheet {
  return {
    on: "2026-11-12",
    currency: "UZS",
    whole_company: true,
    books_start: "2026-09-10",
    assets: {
      sections: [
        {
          key: "cash",
          lines: [
            { key: "cash_on_hand", amount: "33840855.00", count: 7 },
            { key: "bank", amount: "526449411.00", count: 2 },
          ],
          total: "560290266.00",
        },
        { key: "stock", lines: [{ key: "stock_at_cost", amount: "42737620.00" }], total: "42737620.00" },
      ],
      total: "603027886.00",
    },
    liabilities: {
      sections: [{ key: "current", lines: [{ key: "suppliers", amount: "311553200.00", count: 28 }, { key: "loans_current", amount: "66600000.00", count: 1 }], total: "378153200.00" }],
      total: "378153200.00",
    },
    equity: {
      lines: [
        { key: "owner_put_in", amount: "150000000.00" },
        { key: "owner_taken_out", amount: "-41900000.00" },
        { key: "retained", amount: "116774686.00" },
      ],
      total: "224874686.00",
    },
    check: { assets: "603027886.00", liabilities_and_equity: "603027886.00", balanced: true },
    current_assets: "603027886.00",
    current_liabilities: "378153200.00",
    accounts: [],
    foreign: [],
    rate: { rate: "12168.15", stale: false, source: "cbu", date: "2026-11-12" },
    complete: true,
    reconciliation: { lines: [{ key: "profit_recorded", amount: "-54583570.64" }, { key: "stock_at_cost", amount: "42737620.00" }], retained: "116774686.00", unexplained: "0.00" },
    gaps: [{ key: "pending", params: { count: 1, amount: "240000.00" } }],
    ...overrides,
  };
}

function valuation(overrides: Partial<Valuation> = {}): Valuation {
  return {
    on: "2026-11-12",
    currency: "UZS",
    multiple_low: "2.0",
    multiple_high: "3.0",
    default_low: "2.0",
    default_high: "3.0",
    earnings: {
      from: "2026-09-10",
      to: "2026-11-12",
      days: 64,
      enough: true,
      profit: "-40016983.45",
      lines: [
        { key: "profit", amount: "-40016983.45" },
        { key: "depreciation", amount: "4277063.45" },
        { key: "interest", amount: "2800000.00" },
        { key: "equipment", amount: "36800000.00" },
      ],
      earnings: "3860080.00",
      yearly: "22014831.25",
    },
    earnings_method: { applies: true, reason: null, business_low: "44029662.50", business_high: "66044493.75", cash: "560290266.00", debt: "66600000.00", low: "537719928.50", high: "559734759.75" },
    net_assets: { value: "224874686.00", assets: "603027886.00", liabilities: "378153200.00", stock: "42737620.00", fixed_assets: null },
    range: { low: "224874686.00", high: "559734759.75" },
    editable: true,
    ...overrides,
  };
}

function pack(overrides: Partial<StatementPack> = {}): StatementPack {
  return {
    id: 5,
    period: "month",
    start: "2026-10-01",
    end: "2026-10-31",
    purpose: "bank",
    language: "uz",
    branches: null,
    status: "running",
    progress: 40,
    pages: null,
    error: "",
    deliver_telegram: false,
    created_at: "2026-11-12T09:00:00Z",
    finished_at: null,
    expires_at: "2026-11-19T09:00:00Z",
    file_name: null,
    file_url: null,
    ...overrides,
  };
}

const OPTIONS = { today: "2026-11-12", books_start: "2026-09-10", last_activity: "2026-11-12", language: "uz", whole_company: true, may_prepare: true, telegram: true };

describe("period choices", () => {
  it("lists months back to the books' start, the one in progress ending today", () => {
    const months = periodChoices("month", "2026-11-12", "2026-09-10");
    expect(months.map((choice) => [choice.key, choice.end, choice.partial])).toEqual([
      ["2026-11", "2026-11-12", true],
      ["2026-10", "2026-10-31", false],
      ["2026-09", "2026-09-30", false],
    ]);
  });

  it("lists quarters and years, and stops at the limit without a books' start", () => {
    expect(periodChoices("quarter", "2026-11-12", "2026-02-01").map((choice) => choice.key)).toEqual(["2026-Q4", "2026-Q3", "2026-Q2", "2026-Q1"]);
    expect(periodChoices("year", "2026-11-12", "2024-06-01").map((choice) => [choice.key, choice.start])).toEqual([
      ["2026", "2026-01-01"],
      ["2025", "2025-01-01"],
      ["2024", "2024-01-01"],
    ]);
    expect(periodChoices("month", "2026-11-12", null)).toHaveLength(1);
  });
});

describe("the balance sheet tab", () => {
  it("shows both sides, the owners' part, the gaps in words and the balance note", async () => {
    const calls = stub({
      "GET reports/balance-sheet/": () => json(sheet()),
      "GET valuation/": () => json(valuation()),
    });
    const app = await testApp("/c/1/finance/reports/balance-sheet");
    const Report = (await import("../components/statements/BalanceSheetReport.vue")).default;
    mountWithProviders(Report, { props: { branch: [] }, plugins: app.plugins });
    await flushPromises();
    await flushPromises();

    expect([...document.querySelectorAll("[data-section]")].map((el) => el.getAttribute("data-section"))).toEqual(["cash", "stock", "current"]);
    expect(document.querySelector("[data-total-assets]")?.textContent?.replace(/\D/g, "")).toBe("603027886");
    expect([...document.querySelectorAll("[data-equity]")].map((el) => el.getAttribute("data-equity"))).toEqual(["owner_put_in", "owner_taken_out", "retained"]);
    expect(document.querySelector("[data-balanced]")?.textContent).toContain(en["finance.sheet.balancedNote"]);
    expect(document.querySelector("[data-gaps]")?.textContent).toContain("1 entry of");
    expect(document.querySelector("[data-reconciliation]")?.textContent).toContain(en["finance.sheet.line.profit_recorded"]);
    expect(calls.find((call) => call.url.includes("balance-sheet"))?.url).toContain("on=");
    // What the business is worth, both methods on one card.
    expect(document.querySelector("[data-valuation] [data-range]")?.textContent).toContain("–");
    expect(document.querySelector("[data-earnings-bar]")).not.toBeNull();
  });

  it("names a branch's own net assets and leaves the valuation out", async () => {
    stub({
      "GET reports/balance-sheet/": () =>
        json(sheet({ whole_company: false, equity: { lines: [{ key: "net_assets", amount: "114244645.12" }], total: "114244645.12" }, reconciliation: null, gaps: [] })),
      "GET valuation/": () => json({ detail: "Only someone who sees every branch can value the whole business." }, 403),
    });
    const app = await testApp("/c/1/finance/reports/balance-sheet");
    const Report = (await import("../components/statements/BalanceSheetReport.vue")).default;
    mountWithProviders(Report, { props: { branch: [] }, plugins: app.plugins });
    await flushPromises();
    await flushPromises();

    expect(document.querySelector("[data-valuation]")).toBeNull();
    expect(document.querySelector("[data-reconciliation]")).toBeNull();
    expect(document.querySelector("[data-balanced]")?.textContent).toContain(en["finance.sheet.branchNote"]);
    expect(document.querySelector("[data-gaps]")?.textContent).toContain(en["finance.sheet.noGaps"]);
  });
});

describe("what the business is worth", () => {
  it("changes the multiples and shows the answer", async () => {
    const calls = stub({
      "GET valuation/": () => json(valuation()),
      "PATCH valuation/": () => json(valuation({ multiple_low: "1.5", multiple_high: "2.5" })),
    });
    const app = await testApp("/c/1/finance/reports/balance-sheet");
    const Card = (await import("../components/statements/ValuationCard.vue")).default;
    const { wrapper } = mountWithProviders(Card, { plugins: app.plugins });
    await flushPromises();

    document.querySelector<HTMLButtonElement>("[data-how]")!.click();
    await flushPromises();
    expect(document.querySelector("[data-how-body]")?.textContent).toContain(en["finance.worth.line.interest"]);
    document.querySelector<HTMLButtonElement>("[data-edit]")!.click();
    await flushPromises();
    const inputs = wrapper.findAll("[data-multiples] input");
    await inputs[0]!.setValue("1.5");
    await inputs[1]!.setValue("2.5");
    await flushPromises();
    document.querySelector<HTMLButtonElement>("[data-multiples] [data-save]")!.click();
    await flushPromises();
    expect(calls.find((call) => call.method === "PATCH")?.body).toEqual({ multiple_low: "1.5", multiple_high: "2.5" });
  });

  it("says why the earnings method doesn't apply yet", async () => {
    stub({
      "GET valuation/": () =>
        json(
          valuation({
            earnings_method: { applies: false, reason: "too_early", business_low: null, business_high: null, cash: "0.00", debt: "0.00", low: null, high: null },
            earnings: { ...valuation().earnings, days: 34, enough: false, yearly: null },
            range: { low: "224874686.00", high: "224874686.00" },
            editable: false,
          }),
        ),
    });
    const app = await testApp("/c/1/finance/reports/balance-sheet");
    const Card = (await import("../components/statements/ValuationCard.vue")).default;
    mountWithProviders(Card, { plugins: app.plugins });
    await flushPromises();

    expect(document.querySelector("[data-valuation]")?.textContent).toContain("Only 34 days of books");
    expect(document.querySelector("[data-edit]")).toBeNull();
    expect(document.querySelector("[data-earnings-bar]")).toBeNull();
  });
});

describe("preparing the report", () => {
  it("asks for the pack, follows its progress and downloads it", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    let polls = 0;
    const calls = stub({
      "GET statements/options/": () => json(OPTIONS),
      "GET statements/": () => json([]),
      "POST statements/": () => json({ id: 5 }, 202),
      "GET statements/5/": () => {
        polls += 1;
        return json(polls < 2 ? pack() : pack({ status: "ready", progress: 100, pages: 9, file_url: "/api/v1/files/x/", file_name: "hisobot.pdf" }));
      },
    });
    const app = await testApp("/c/1/finance/reports/balance-sheet");
    const Dialog = (await import("../components/statements/PrepareReportDialog.vue")).default;
    mountWithProviders(Dialog, { props: { open: true }, plugins: app.plugins });
    await flushPromises();
    await flushPromises();

    document.querySelector<HTMLButtonElement>("[data-prepare]")!.click();
    await flushPromises();
    await vi.advanceTimersByTimeAsync(1500);
    await flushPromises();
    await vi.advanceTimersByTimeAsync(1500);
    await flushPromises();

    const posted = calls.find((call) => call.method === "POST")!;
    // October, the last full month, for a bank, in the person's language.
    expect(posted.body).toEqual({ period: "month", of: "2026-10-01", purpose: "bank", language: "uz", deliver_telegram: false });
    expect(click).toHaveBeenCalled();
    expect(document.body.textContent).toContain(en["finance.pack.ready"]);
    vi.useRealTimers();
  });

  it("the button needs the export permission", async () => {
    const app = await testApp("/c/2/finance/reports/balance-sheet");
    useSessionStore().me = me([company(), manager(["finance.view"], { features: ["finance"] })]);
    const { useCompanyStore } = await import("@/stores/company");
    useCompanyStore().setCurrent(2);
    const Button = (await import("../components/statements/PrepareReportButton.vue")).default;
    mountWithProviders(Button, { plugins: app.plugins });
    await flushPromises();
    expect(document.querySelector("[data-prepare-report]")).toBeNull();
  });
});
