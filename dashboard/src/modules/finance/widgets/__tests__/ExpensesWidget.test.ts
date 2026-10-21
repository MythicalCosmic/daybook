// The Overview's "Expenses this month" tile: it opens the rows it counts, and no two of its parts
// look alike.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import ExpensesWidget from "../ExpensesWidget.vue";

afterEach(() => vi.unstubAllGlobals());

const month = { from: "2026-10-01", to: "2026-10-21", income: "377600000.00", expense: "336500000.00", profit: "41100000.00", previous: { from: "2026-09-01", to: "2026-09-21", income: "0", expense: "350000000.00", profit: "0" } };

describe("ExpensesWidget", () => {
  it("links to the month's expense rows by the P&L filter and gives categories distinct colours", async () => {
    // Two categories with the same colour, and one tiny share.
    const top_expenses = [
      { id: 7, name: "Dori va tovar xaridi", color: "#3d6a8c", amount: "265000000.00" },
      { id: 9, name: "Uskunalar", color: "#3d6a8c", amount: "23500000.00" },
      { id: 4, name: "Ijara", color: "", amount: "1000000.00" },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string) => (String(input).includes("/finance/overview/") ? json({ month, top_expenses }) : json({ detail: "Not found." }, 404))),
    );
    const app = await testApp("/c/1");
    const { wrapper } = mountWithProviders(ExpensesWidget, { plugins: app.plugins, props: { companyId: 1 } });
    await flushPromises();
    const href = wrapper.get("a").attributes("href")!;
    expect(href).toContain("/c/1/finance/transactions?");
    expect(href).toContain("pnl=expense");
    expect(href).toContain("from=2026-10-01");
    expect(href).toContain("to=2026-10-21");
    const swatches = wrapper.findAll("li span[aria-hidden='true']").map((dot) => dot.attributes("style"));
    expect(new Set(swatches).size).toBe(3);
    // A sliver of the month says so, not "0%".
    expect(wrapper.text()).toContain("<1%");
    wrapper.unmount();
  });
});
