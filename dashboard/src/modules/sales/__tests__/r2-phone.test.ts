// Round 2, phones (the owner's console inside Telegram): a voided receipt or movement must not
// look like a sale on the card list, and Void is reachable there too.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { ensureModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import salesModule from "..";
import en from "../i18n/en.json";

// Whole pages and dialogs mount here: slow while the rest of the suite runs beside them.
vi.setConfig({ testTimeout: 20_000 });

beforeAll(() => {
  // Phone width before anything reads the shared breakpoints.
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("max-width: 767.98px"), media: query, addEventListener: () => undefined, removeEventListener: () => undefined }));
});

afterEach(() => {
  document.body.innerHTML = "";
});

function stub(routes: Record<string, () => Response>): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const path = input.replace("/api/v1/owner/companies/1/", "").split("?")[0]!;
      return routes[`${init?.method ?? "GET"} ${path}`]?.() ?? json({ detail: "Not found." }, 404);
    }),
  );
}

const options = () => ({
  currency: "UZS",
  settings: { mode: "receipts", blind_cash_count: true, cash_tolerance: "5000.00", business_day_ends_at: "04:00" },
  today: "2026-10-21",
  branches: [{ id: 1, name: "Chilonzor", code: "CHL" }],
  registers: [{ id: 5, name: "Kassa 1", branch_id: 1, branch: "Chilonzor", is_active: true }],
  methods: [],
  cashiers: [],
  receivers: [],
  categories: [],
  accounts: [],
});

const page = <T>(results: T[]) => ({ count: results.length, next: null, previous: null, results });

describe("payment methods on a phone", () => {
  it("can still be put in order (the arrows were desktop-only)", async () => {
    const method = (id: number, name: string) => ({ id, name, kind: "card", account: null, fee_percent: "0.00", is_active: true, order: id, is_default: false });
    const calls: Array<{ url: string; body: unknown }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string, init?: RequestInit) => {
        calls.push({ url: input, body: init?.body ? JSON.parse(String(init.body)) : undefined });
        if (input.includes("payment-methods/reorder/")) return json([method(2, "Uzcard"), method(1, "Naqd")]);
        if (input.includes("payment-methods/")) return json([method(1, "Naqd"), method(2, "Uzcard")]);
        return json(options());
      }),
    );
    const PaymentMethodsPanel = (await import("../components/PaymentMethodsPanel.vue")).default;
    const DropdownMenu = (await import("@/components/DropdownMenu.vue")).default;
    const app = await testApp("/c/1/sales/setup");
    await ensureModuleMessages(salesModule);
    const { wrapper } = mountWithProviders(PaymentMethodsPanel, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    const menus = wrapper.findAllComponents(DropdownMenu);
    expect(menus).toHaveLength(2);
    const items = menus[0]!.props("items") as Array<{ label: string; onSelect: () => void }>;
    items.find((item) => item.label === en["sales.methods.down"])!.onSelect();
    await flushPromises();
    expect(calls.find((c) => c.url.includes("reorder/"))?.body).toEqual({ ids: [2, 1] });
    wrapper.unmount();
  });
});

describe("sales phone cards", () => {
  it("marks a voided receipt and a refund, and offers Void on the others", async () => {
    const entry = (id: number, extra: Record<string, unknown>) => ({
      id,
      kind: "sale",
      number: String(id),
      total: "250000.00",
      discount: "0.00",
      branch: { id: 1, name: "Chilonzor", code: "CHL" },
      register: null,
      shift: null,
      cashier: null,
      performed_by: null,
      sold_at: "2026-10-21T10:00:00+05:00",
      business_day: "2026-10-21",
      source: "dashboard",
      note: "",
      payments: [],
      voided_at: null,
      void_reason: "",
      ...extra,
    });
    stub({ "GET sales/options/": () => json(options()), "GET sales/entries/": () => json(page([entry(1, { voided_at: "2026-10-21T11:00:00+05:00" }), entry(2, { kind: "refund" }), entry(3, {})])) });
    const EntriesPage = (await import("../pages/EntriesPage.vue")).default;
    const app = await testApp("/c/1/sales/entries");
    await ensureModuleMessages(salesModule);
    const { wrapper } = mountWithProviders(EntriesPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    const cards = [...document.querySelectorAll("ul li")];
    expect(cards).toHaveLength(3);
    expect(cards[0]!.textContent).toContain(en["sales.movement.status.void"]);
    expect(cards[1]!.textContent).toContain(en["sales.entries.refund"]);
    // Void on the two that stand, none on the voided one.
    expect(document.querySelectorAll(`ul li button[aria-label="${en["sales.cash.void"]}"]`)).toHaveLength(2);
    wrapper.unmount();
  });

  it("shows a cash movement's status and Void on its card", async () => {
    const movement = (id: number, status: string) => ({
      id,
      kind: "payout",
      status,
      amount: "50000.00",
      currency: "UZS",
      branch: { id: 1, name: "Chilonzor", code: "CHL" },
      register: { id: 5, name: "Kassa 1" },
      shift: null,
      receiver: null,
      to_account: null,
      category: null,
      reason: "Svet",
      photo: null,
      created_by: { id: 16, name: "Madina Saidova" },
      created_at: "2026-10-21T10:00:00+05:00",
      confirmed_at: null,
      confirmed_by: null,
      declined_at: null,
      decline_reason: "",
      voided_at: status === "void" ? "2026-10-21T11:00:00+05:00" : null,
    });
    stub({
      "GET sales/options/": () => json(options()),
      "GET sales/cash/positions/": () => json({ currency: "UZS", registers: [], safes: [], people: [], in_transit: [] }),
      "GET sales/cash-movements/": () => json(page([movement(1, "void"), movement(2, "done")])),
    });
    const CashPage = (await import("../pages/CashPage.vue")).default;
    const app = await testApp("/c/1/sales/cash");
    await ensureModuleMessages(salesModule);
    const { wrapper } = mountWithProviders(CashPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    const cards = [...document.querySelectorAll("ul li")].filter((li) => li.textContent?.includes(en["sales.movement.kind.payout"]));
    expect(cards).toHaveLength(2);
    expect(cards[0]!.textContent).toContain(en["sales.movement.status.void"]);
    expect(cards[1]!.querySelector(`button[aria-label="${en["sales.cash.void"]}"]`)).not.toBeNull();
    expect(cards[0]!.querySelector(`button[aria-label="${en["sales.cash.void"]}"]`)).toBeNull();
    wrapper.unmount();
  });
});
