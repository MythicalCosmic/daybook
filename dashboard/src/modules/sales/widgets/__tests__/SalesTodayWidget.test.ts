// The Overview's "Sales yesterday" tile: its trend ends on the day its number is about.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import KpiCard from "@/components/KpiCard.vue";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import SalesTodayWidget from "../SalesTodayWidget.vue";

afterEach(() => vi.unstubAllGlobals());

describe("SalesTodayWidget", () => {
  it("ends yesterday's trend yesterday, with its first and last day under it", async () => {
    // Today's point stays empty until a shift closes (Z-report): it is not a day of zero sales.
    const series = Array.from({ length: 14 }, (_, i) => ({ date: `2026-10-${String(8 + i).padStart(2, "0")}`, net: i === 13 ? null : String(15_000_000 + i * 100_000), receipts: i === 13 ? null : 300 }));
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string) =>
        String(input).includes("/sales/summary/") ? json({ range: { from: "2026-10-08", to: "2026-10-21" }, compare: null, totals: {}, series, breakdown: [] }) : json({ detail: "Not found." }, 404),
      ),
    );
    const app = await testApp("/c/1");
    const { wrapper } = mountWithProviders(SalesTodayWidget, { plugins: app.plugins, props: { companyId: 1 } });
    await flushPromises();
    const tile = wrapper.findComponent(KpiCard);
    expect(tile.props("value")).toBe("16200000");
    expect(tile.props("spark")).toHaveLength(13);
    expect(tile.props("spark")!.at(-1)).toBe("16200000");
    expect(tile.props("sparkLabels")).toEqual(["8 Oct", "Yesterday"]);
    wrapper.unmount();
  });
});
