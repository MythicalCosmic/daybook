// The registry first, as in the app.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ensureModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import salesModule from "..";
import { salesApi } from "../api";
import ShiftDrawer from "../components/ShiftDrawer.vue";
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
