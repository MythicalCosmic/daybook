// The registry first, as in the app.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h, ref } from "vue";

import { ensureModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import salesModule from "..";
import { salesApi } from "../api";
import ShiftDrawer from "../components/ShiftDrawer.vue";
import TodayBranches from "../components/TodayBranches.vue";
import { countRows, differenceLevel, movementSign } from "../format";
import type { ShiftDetail } from "../types";

interface Call {
  method: string;
  url: string;
  body: unknown;
}

function stub(routes: Record<string, (call: Call) => Response | Promise<Response>>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const call = { method: init?.method ?? "GET", url: input, body: init?.body ? JSON.parse(String(init.body)) : undefined };
      calls.push(call);
      const path = input.replace("/api/v1/owner/companies/1/", "").split("?")[0]!;
      return routes[`${call.method} ${path}`]?.(call) ?? json({ detail: "Not found." }, 404);
    }),
  );
  return calls;
}

const person = (id: number, name: string) => ({ id, name });

function shift(extra: Partial<ShiftDetail> = {}): ShiftDetail {
  return {
    id: 42,
    code: "CHL-42",
    number: 42,
    branch: { id: 1, name: "Chilonzor", code: "CHL" },
    register: { id: 3, name: "Kassa 1" },
    cashier: person(16, "Madina Saidova"),
    business_day: "2026-10-20",
    status: "closed",
    opened_at: "2026-10-20T03:56:00Z",
    closed_at: "2026-10-20T16:11:00Z",
    opening_float: "200000.00",
    net: "14414000.00",
    receipts: 165,
    expected_cash: "4230000.00",
    counted_cash: "4215000.00",
    difference: "-15000.00",
    forced: false,
    ai_mismatch: false,
    verified_by: null,
    verified_at: null,
    has_photos: true,
    payments: [
      { method: { id: 1, name: "Naqd", kind: "cash" }, sales: "6357000.00", refunds: "0.00", net: "6357000.00", receipts: 0, fee: "0.00" },
      { method: { id: 2, name: "Uzcard", kind: "card" }, sales: "8057000.00", refunds: "0.00", net: "8057000.00", receipts: 0, fee: "80570.00" },
    ],
    cash_flow: {
      opening_float: "200000.00",
      cash_sales: "6357000.00",
      cash_refunds: "0.00",
      payout: "327000.00",
      deposit: "0.00",
      handover: "2000000.00",
      to_safe: "0.00",
      from_safe: "0.00",
      to_bank: "0.00",
      expected: "4230000.00",
    },
    opening_count: { "10000": 10, "5000": 10, "2000": 10, "1000": 30 },
    closing_count: { "200000": 15, "100000": 12 },
    expected_float: "200000.00",
    float_difference: "0.00",
    recount_cash: null,
    cashier_counted: "4215000.00",
    fiscal_cash_total: "6357000.00",
    fiscal_card_total: "8057000.00",
    z_number: "0495",
    z_photo: null,
    terminal_photo: null,
    ai_reading: {},
    cashier_note: "",
    note: "",
    closed_by: person(16, "Madina Saidova"),
    movements: [],
    receipts_recorded: 0,
    ledger: [],
    actions: { verify: true, dispute: true, correct: true, force_close: false },
    tolerance: "5000.00",
    timeline: [],
    ...extra,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("sales display rules", () => {
  it("reads a difference against the tolerance", () => {
    expect(differenceLevel(null, "5000")).toBe("unknown");
    expect(differenceLevel("0.00", "5000")).toBe("none");
    expect(differenceLevel("-3000.00", "5000.00")).toBe("ok");
    expect(differenceLevel("-15000.00", "5000.00")).toBe("short");
    expect(differenceLevel("12000.00", "5000.00")).toBe("over");
  });

  it("signs movements and orders a banknote count", () => {
    expect(movementSign("from_safe")).toBe(1);
    expect(movementSign("handover")).toBe(-1);
    expect(countRows({ "1000": 30, "200000": 3, "5000": 0 })).toEqual([
      ["200000", 3],
      ["1000", 30],
    ]);
  });
});

describe("sales API", () => {
  it("sends shift filters as repeated query parameters", async () => {
    const calls = stub({ "GET sales/shifts/": () => json({ count: 0, next: null, previous: null, results: [] }) });
    await salesApi.shifts(1, { status: ["closed", "disputed"], branch: ["3"], has_difference: "1", page: 2 });
    const url = new URL(calls[0]!.url, "http://x");
    expect(url.pathname).toBe("/api/v1/owner/companies/1/sales/shifts/");
    expect(url.searchParams.getAll("status")).toEqual(["closed", "disputed"]);
    expect(url.searchParams.get("has_difference")).toBe("1");
    expect(url.searchParams.get("page")).toBe("2");
  });

  it("verifies with a recount and corrects with payment lines", async () => {
    const calls = stub({
      "POST sales/shifts/42/verify/": () => json(shift({ status: "verified" })),
      "PATCH sales/shifts/42/payments/": () => json(shift()),
    });
    await salesApi.verify(1, 42, { recount_cash: "4220000", note: "Recounted" });
    await salesApi.correct(1, 42, { payments: [{ method_id: 1, sales: "6400000" }], reason: "Typo", counted_cash: null });
    expect(calls[0]!.body).toEqual({ recount_cash: "4220000", note: "Recounted" });
    expect(calls[1]).toMatchObject({ method: "PATCH", body: { payments: [{ method_id: 1, sales: "6400000" }], reason: "Typo", counted_cash: null } });
  });
});

describe("TodayBranches", () => {
  it("shows who opened each branch, its open tills and its cash against the limit", async () => {
    stub({
      "GET sales/today/": () =>
        json({
          branches: [
            {
              id: 1,
              name: "Chilonzor",
              code: "CHL",
              status: "open",
              opens_at: "09:00",
              closes_at: "21:00",
              opened_at: "2026-10-21T09:40:00+05:00",
              opened_by: person(16, "Madina Saidova"),
              open_tills: [{ register: { id: 3, name: "Kassa 1" }, shift: { id: 85, code: "CHL-85", since: "2026-10-21T04:40:00Z" }, cashier: person(16, "Madina Saidova"), amount: "1509000.00" }],
              tills: 2,
              net: "11700000.00",
              receipts: 129,
              cash_in_branch: "6500000.00",
              cash_limit: "20000000.00",
              target: null,
              alerts: [{ kind: "difference", severity: "critical", shift: { id: 84, code: "CHL-84" }, amount: "-582000.00" }],
            },
          ],
        }),
    });
    const app = await testApp("/c/1/sales");
    await ensureModuleMessages(salesModule);
    mountWithProviders(TodayBranches, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    const text = document.body.textContent ?? "";
    expect(text).toContain("Chilonzor");
    expect(text).toContain("Madina");
    expect(text).toContain("CHL-85");
    expect(text).toContain("limit");
    expect(text).toContain("CHL-84");
    // The open tills count stands in for the target when there is none.
    expect(text).toContain("1 / 2");
  });

  it("shows no sales yet (not zero) while tills are open in shift-totals mode, and the month in the language's percent", async () => {
    stub({
      "GET sales/options/": () => json(options()),
      "GET sales/today/": () =>
        json({
          branches: [
            {
              id: 1,
              name: "Chilonzor",
              code: "CHL",
              status: "open",
              opens_at: "09:00",
              closes_at: "21:00",
              opened_at: "2026-10-21T08:40:00+05:00",
              opened_by: person(16, "Madina Saidova"),
              open_tills: [{ register: { id: 3, name: "Kassa 1" }, shift: { id: 85, code: "CHL-85", since: "2026-10-21T03:40:00Z" }, cashier: person(16, "Madina Saidova"), amount: "110000.00" }],
              tills: 2,
              net: "0.00",
              receipts: 0,
              cash_in_branch: "1110000.00",
              cash_limit: "20000000.00",
              target: { amount: "450000000.00", actual: "342400000.00", pace: "305000000.00", projected: "505000000.00", percent: "76.1", days: 31, elapsed: 21, per_day_needed: "10800000.00", ahead: true },
              alerts: [],
            },
          ],
        }),
    });
    const app = await testApp("/c/1/sales");
    await ensureModuleMessages(salesModule);
    mountWithProviders(TodayBranches, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    const text = document.body.textContent ?? "";
    expect(document.querySelector('[data-testid="today-awaiting"]')?.textContent).toBe("—");
    expect(text).toContain("sales added at close");
    expect(text).not.toContain("0 receipts");
    expect(text).toContain("This month · 76.1%");
  });
});

function options(mode: "shift_totals" | "receipts" = "shift_totals") {
  return {
    currency: "UZS",
    settings: { mode, blind_cash_count: true, cash_tolerance: "5000.00", business_day_ends_at: "04:00" },
    today: "2026-10-21",
    branches: [{ id: 1, name: "Chilonzor", code: "CHL" }],
    registers: [],
    methods: [],
    cashiers: [],
    receivers: [],
    categories: [],
    accounts: [],
  };
}

describe("MovementDialog", () => {
  it("names each till with its branch, since every branch has a Kassa 1", async () => {
    stub({
      "GET sales/options/": () =>
        json({
          ...options(),
          registers: [
            { id: 5, name: "Kassa 1", branch_id: 1, branch: "Chilonzor", is_active: true },
            { id: 6, name: "Kassa 1", branch_id: 2, branch: "Yunusobod", is_active: true },
          ],
        }),
    });
    const MovementDialog = (await import("../components/MovementDialog.vue")).default;
    const app = await testApp("/c/1/sales/cash");
    await ensureModuleMessages(salesModule);
    const open = ref(false);
    const Host = defineComponent({ setup: () => () => h(MovementDialog, { open: open.value, "onUpdate:open": (value: boolean) => (open.value = value) }) });
    mountWithProviders(Host, { plugins: app.plugins });
    await flushPromises();
    open.value = true; // opening picks the first till
    await flushPromises();
    await flushPromises();
    expect(document.body.textContent).toContain("Chilonzor · Kassa 1");
  });
});

describe("ShiftsPage", () => {
  const row = (extra: Record<string, unknown>) => ({
    id: 85,
    code: "CHL-85",
    number: 85,
    branch: { id: 1, name: "Chilonzor", code: "CHL" },
    register: { id: 3, name: "Kassa 1" },
    cashier: person(16, "Madina Saidova"),
    business_day: "2026-10-21",
    status: "open",
    opened_at: "2026-10-21T03:40:00Z",
    closed_at: null,
    opening_float: "110000.00",
    net: "0.00",
    receipts: 0,
    expected_cash: null,
    counted_cash: null,
    difference: null,
    forced: false,
    ai_mismatch: false,
    verified_by: null,
    verified_at: null,
    has_photos: false,
    ...extra,
  });

  it("marks an open till's sales as still to come in shift-totals mode, and shows a closed one's", async () => {
    stub({
      "GET sales/options/": () => json(options()),
      "GET sales/settings/": () => json({ mode: "shift_totals", cash_tolerance: "5000.00" }),
      "GET sales/shifts/": () =>
        json({ count: 2, next: null, previous: null, results: [row({}), row({ id: 84, code: "CHL-84", status: "closed", net: "14414000.00", receipts: 165, counted_cash: "230000.00", difference: "0.00", closed_at: "2026-10-20T16:11:00Z" })] }),
    });
    const ShiftsPage = (await import("../pages/ShiftsPage.vue")).default;
    const app = await testApp("/c/1/sales/shifts?view=all");
    await ensureModuleMessages(salesModule);
    mountWithProviders(ShiftsPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    await flushPromises();
    const awaiting = document.querySelectorAll('[data-testid="net-awaiting"]');
    expect(awaiting).toHaveLength(1);
    expect(awaiting[0]!.getAttribute("title")).toBe("sales added at close");
    expect(document.body.textContent).toContain("14,414,000");
  });
});

describe("ShiftDrawer on an open till", () => {
  it("shows the cash taken out instead of a negative expected cash before the close", async () => {
    stub({
      "GET sales/shifts/42/": () =>
        json(
          shift({
            status: "open",
            closed_at: null,
            net: "0.00",
            payments: [],
            expected_cash: null,
            counted_cash: null,
            difference: null,
            receipts_recorded: 0,
            cash_flow: { opening_float: "1509000.00", cash_sales: "0.00", cash_refunds: "0.00", payout: "165000.00", deposit: "0.00", handover: "1500000.00", to_safe: "2000000.00", from_safe: "0.00", to_bank: "0.00", expected: "-2156000.00" },
            actions: { verify: false, dispute: false, correct: false, force_close: true },
          }),
        ),
    });
    const app = await testApp("/c/1/sales/shifts?shift=42");
    await ensureModuleMessages(salesModule);
    mountWithProviders(ShiftDrawer, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    const text = document.body.textContent ?? "";
    expect(text).toContain("Cash out so far");
    expect(text).toContain("sales added at close");
    expect(text).not.toContain("Expected cash");
  });
});

describe("ShiftDrawer", () => {
  it("shows the four numbers and verifies the shift", async () => {
    const calls = stub({
      "GET sales/shifts/42/": () => json(shift()),
      "POST sales/shifts/42/verify/": () => json(shift({ status: "verified", verified_by: person(13, "Dilnoza Karimova"), actions: { verify: false, dispute: false, correct: true, force_close: false } })),
    });
    const app = await testApp("/c/1/sales/shifts?shift=42");
    await ensureModuleMessages(salesModule);
    mountWithProviders(ShiftDrawer, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    const body = document.body;
    expect(body.textContent).toContain("CHL-42");
    expect(body.textContent).toContain("Madina Saidova");
    expect(body.textContent).toContain("Net sales");
    const verify = [...body.querySelectorAll("button")].find((button) => button.textContent?.trim().startsWith("Verify"))!;
    verify.click();
    await flushPromises();
    expect(body.textContent).toContain("Verify CHL-42");
    const submit = [...body.querySelectorAll("button")].find((button) => button.textContent?.trim() === "Verify shift")!;
    submit.click();
    await flushPromises();
    await flushPromises();
    const post = calls.find((call) => call.method === "POST");
    expect(post?.url).toBe("/api/v1/owner/companies/1/sales/shifts/42/verify/");
    expect(post?.body).toEqual({ recount_cash: null, note: "" });
  });
});
