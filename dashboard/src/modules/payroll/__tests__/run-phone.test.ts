// A run on a phone (the owner inside Telegram): each payslip card's line of parts shows extra
// pay, taxes and expenses paid back too, as the server sent them, so the card adds up to its net.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import en from "../i18n/en.json";
import type { Payslip, Run } from "../types";

vi.setConfig({ testTimeout: 20_000 });

beforeAll(() => {
  // Phone width before anything reads the shared breakpoints.
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("max-width: 767.98px"), media: query, addEventListener: () => undefined, removeEventListener: () => undefined }));
});

beforeEach(() => {
  mergeModuleMessages("payroll", { en, ru: en, uz: en });
});

afterEach(() => {
  document.body.innerHTML = "";
});

const page = <T>(results: T[]) => ({ count: results.length, next: null, previous: null, results });

const draft: Run = {
  id: 7,
  period: "2026-10-01",
  kind: "regular",
  status: "draft",
  member: null,
  usd_rate: null,
  calculated_at: "2026-11-01T06:00:00+05:00",
  finalized_at: null,
  finalized_by: null,
  paid_at: null,
  notes: "",
  warnings: [],
  totals: { currency: "UZS", people: 1, gross: "6150000.00", deductions: "50000.00", net: "6100000.00", paid: 0, published: 0 },
};

// Deliberately not adding up: the card must show the server's strings, not work anything out.
const slip: Payslip = {
  id: 1,
  run: 7,
  period: "2026-10-01",
  member: { id: 10, name: "Aziza Rasulova" },
  currency: "UZS",
  pay_type: "monthly",
  base_pay: "6000000.00",
  extras: "111.11",
  bonuses: "0.00",
  fines: "-50000.00",
  advances: "0.00",
  taxes_withheld: "-624000.00",
  reimbursements: "150000.00",
  net: "6323000.00",
  status: "draft",
  published_at: null,
  viewed_at: null,
  paid_at: null,
  payout_method: "",
  received_at: null,
};

describe("a run on a phone", () => {
  it("each card's parts are the API's strings, extra pay, taxes and expenses paid back included", async () => {
    vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string) => {
        const path = input.replace(/^.*\/api\/v1\/owner\/companies\/1\//, "").split("?")[0]!;
        if (path === "payroll/runs/7/") return json(draft);
        if (path === "payroll/runs/7/payslips/") return json(page([slip]));
        return json({ detail: "Not found." }, 404);
      }),
    );
    const RunPage = (await import("../pages/RunPage.vue")).default;
    const app = await testApp("/c/1/payroll");
    app.router.addRoute({ path: "/c/:companyId/payroll/runs/:runId(\\d+)", component: { render: () => null } });
    await app.router.replace("/c/1/payroll/runs/7");
    mountWithProviders(RunPage, { plugins: app.plugins });
    for (let i = 0; i < 4; i += 1) await flushPromises();
    const line = document.querySelector('[data-testid="card-breakdown"]')?.textContent?.replace(/\s+/g, " ") ?? "";
    expect(line).toContain("Base 6,000,000");
    expect(line).toContain("Extra pay +111.11");
    expect(line).toContain("Fines −50,000");
    expect(line).toContain("Taxes −624,000");
    expect(line).toContain("Reimbursed +150,000");
    // Zero parts stay out of the line.
    expect(line).not.toContain("Bonuses");
    expect(line).not.toContain("Advances");
  });
});
