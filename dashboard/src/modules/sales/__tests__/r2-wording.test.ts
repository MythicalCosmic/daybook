// Round 2: numbers and month names written the language's way.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ensureModuleMessages, setLanguage } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import salesModule from "..";

// Whole pages and dialogs mount here: slow while the rest of the suite runs beside them.
vi.setConfig({ testTimeout: 20_000 });

function stub(routes: Record<string, () => Response>): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const path = input.replace("/api/v1/owner/companies/1/", "").split("?")[0]!;
      return routes[`${init?.method ?? "GET"} ${path}`]?.() ?? json({ detail: "Not found." }, 404);
    }),
  );
}

afterEach(async () => {
  vi.unstubAllGlobals();
  await setLanguage("en");
  document.body.innerHTML = "";
});

const options = () => ({
  currency: "UZS",
  settings: { mode: "shift_totals", blind_cash_count: true, cash_tolerance: "5000.00", business_day_ends_at: "04:00" },
  today: "2026-10-21",
  branches: [{ id: 1, name: "Chilonzor", code: "CHL" }],
  registers: [],
  methods: [],
  cashiers: [],
  receivers: [],
  categories: [],
  accounts: [],
});

describe("sales wording", () => {
  it("writes the month heading with one capital letter: 'Октябрь 2026 г.', not 'Октябрь 2026 Г.'", async () => {
    stub({ "GET sales/options/": () => json(options()), "GET sales/targets/": () => json({ month: "2026-10", today: "2026-10-21", targets: [], series: [] }) });
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe(): void {}
        unobserve(): void {}
        disconnect(): void {}
      },
    );
    const TargetsPage = (await import("../pages/TargetsPage.vue")).default;
    const app = await testApp("/c/1/sales/targets?month=2026-10", "ru");
    await ensureModuleMessages(salesModule);
    const { wrapper } = mountWithProviders(TargetsPage, { plugins: app.plugins });
    await flushPromises();
    const heading = wrapper.find('[data-testid="target-month"]');
    expect(heading.text()).toBe("Октябрь 2026 г.");
    expect(heading.classes()).not.toContain("capitalize");
    wrapper.unmount();
  });

  it("writes a cashier's average hours with the language's decimal comma", async () => {
    const score = {
      member: { id: 16, name: "Madina Saidova" },
      branches: ["Chilonzor"],
      shifts: 4,
      net: "14414000.00",
      avg_per_shift: "3603500.00",
      receipts: 165,
      avg_check: "87357.00",
      accuracy: "0.98",
      shortages: 0,
      surpluses: 0,
      shortage_total: "0.00",
      surplus_total: "0.00",
      difference_total: "0.00",
      verified: 4,
      disputed: 0,
      forced: 0,
      late_opens: 0,
      avg_hours: "7.5",
      last_shift_at: null,
    };
    stub({ "GET sales/options/": () => json(options()), "GET sales/cashiers/": () => json({ range: { from: "2026-10-01", to: "2026-10-21" }, results: [score] }) });
    // The hours column is hidden until shown: show it, as the column picker would.
    const { writeStored } = await import("@/lib/storage");
    writeStored("table.sales.cashiers.hidden", []);
    const CashiersPage = (await import("../pages/CashiersPage.vue")).default;
    const app = await testApp("/c/1/sales/cashiers", "ru");
    await ensureModuleMessages(salesModule);
    const { wrapper } = mountWithProviders(CashiersPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    expect(document.body.textContent).toContain("7,5 ч");
    expect(document.body.textContent).not.toContain("7.5 ч");
    wrapper.unmount();
  });
});
