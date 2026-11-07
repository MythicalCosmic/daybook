// Customers with aging and invoices (plan §11.4): the pages show what customers owe by age, the
// invoices' status and what is overdue, and the invoice actions call the sales API.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mergeModuleMessages, setLanguage } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import { salesApi } from "../api";
import en from "../i18n/en.json";
import ru from "../i18n/ru.json";
import uz from "../i18n/uz.json";
import CustomersPage from "../pages/CustomersPage.vue";
import InvoicesPage from "../pages/InvoicesPage.vue";

type Call = { method: string; url: string; body: unknown };

function stub(routes: Record<string, () => Response>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const call = { method: init?.method ?? "GET", url: input, body: init?.body && typeof init.body === "string" ? JSON.parse(init.body) : undefined };
      calls.push(call);
      const path = input.replace("/api/v1/owner/companies/1/", "").split("?")[0]!;
      return routes[`${call.method} ${path}`]?.() ?? json({ detail: "Not found." }, 404);
    }),
  );
  return calls;
}

const page = <T>(results: T[]) => ({ count: results.length, next: null, previous: null, results });
const options = {
  currency: "UZS",
  settings: { mode: "shift_totals", blind_cash_count: true, cash_tolerance: "5000.00", business_day_ends_at: "04:00", sales_lines: "none" },
  today: "2026-11-07",
  branches: [{ id: 1, name: "Chilonzor", code: "CHL" }],
  registers: [],
  methods: [],
  cashiers: [],
  receivers: [],
  categories: [],
  accounts: [{ id: 5, name: "Bank", kind: "bank", branch_id: null }],
};

beforeEach(() => mergeModuleMessages("sales", { en, ru, uz }));
afterEach(async () => {
  vi.unstubAllGlobals();
  await setLanguage("en");
  document.body.innerHTML = "";
});

describe("CustomersPage", () => {
  it("shows the receivables by age and who owes what", async () => {
    stub({
      "GET sales/receivables/aging/": () =>
        json({ currency: "UZS", today: "2026-11-07", totals: { not_due: "100000.00", d0_30: "50000.00", d31_60: "0.00", d60_plus: "20000.00" }, total: "170000.00", customers: [] }),
      "GET sales/customers/": () =>
        json(page([{ id: 3, name: "Saida Rahimova", kind: "person", phone: "+998901112233", tin: "", telegram_username: "", contact_person: "", address: "", notes: "", credit_limit: "500000.00", credit_blocked: false, is_active: true, owed: "170000.00", currency: "UZS" }])),
    });
    const app = await testApp("/c/1/sales/customers");
    mountWithProviders(CustomersPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    const text = document.body.textContent ?? "";
    expect(text).toContain("Saida Rahimova");
    expect(text).toContain(en["sales.customers.aging.d60_plus"]);
    expect(text).toContain(en["sales.customers.kinds.person"]);
  });
});

describe("InvoicesPage", () => {
  it("marks what is overdue", async () => {
    stub({
      "GET sales/options/": () => json(options),
      "GET sales/invoices/": () =>
        json(page([{ id: 7, number: "INV-SRG-0001", status: "issued", customer: { id: 3, name: "Oydin dorixonasi" }, branch: null, currency: "UZS", subtotal: "500000.00", discount: "0.00", total: "500000.00", paid: "0.00", left: "500000.00", issued_on: "2026-10-01", due_on: "2026-10-08", overdue: true, sent_at: null, e_invoice_ref: "", created_at: "2026-10-01T05:00:00Z" }])),
    });
    const app = await testApp("/c/1/sales/invoices");
    mountWithProviders(InvoicesPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    const text = document.body.textContent ?? "";
    expect(text).toContain("INV-SRG-0001");
    expect(text).toContain(en["sales.invoices.overdue"]);
  });

  it("issues, pays and sends through the sales API", async () => {
    const calls = stub({
      "POST sales/invoices/7/issue/": () => json({ id: 7 }),
      "POST sales/invoices/7/payments/": () => json({ id: 7 }),
      "POST sales/invoices/7/send/": () => json({ delivered: "link", url: "/api/v1/files/x/" }),
    });
    await salesApi.issueInvoice(1, 7);
    await salesApi.payInvoice(1, 7, { account_id: 5, amount: "250000", paid_on: "2026-11-07" });
    const sent = await salesApi.sendInvoice(1, 7);
    expect(calls.map((call) => `${call.method} ${call.url.replace("/api/v1/owner/companies/1/", "")}`)).toEqual([
      "POST sales/invoices/7/issue/",
      "POST sales/invoices/7/payments/",
      "POST sales/invoices/7/send/",
    ]);
    expect(calls[1]!.body).toEqual({ account_id: 5, amount: "250000", paid_on: "2026-11-07" });
    expect(sent.delivered).toBe("link");
  });
});
