// Widgets other modules register on the Overview, as the cockpit shows them: each says a thing
// once, and a trend ends on the day its number is about.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import KpiCard from "@/components/KpiCard.vue";
import { mergeModuleMessages } from "@/i18n";
import attendanceEn from "@/modules/attendance/i18n/en.json";
import PresentWidget from "@/modules/attendance/widgets/PresentWidget.vue";
import SalesTodayWidget from "@/modules/sales/widgets/SalesTodayWidget.vue";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

function stub(routes: Record<string, () => Response>): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string) => {
      const path = input.replace("/api/v1/owner/companies/1/", "").split("?")[0]!;
      return routes[path]?.() ?? json({ detail: "Not found." }, 404);
    }),
  );
}

const mounted: Array<{ unmount: () => void }> = [];
afterEach(() => {
  mounted.splice(0).forEach((wrapper) => wrapper.unmount());
  vi.unstubAllGlobals();
});

async function mountWidget(component: object) {
  const app = await testApp("/c/1");
  const { wrapper } = mountWithProviders(component, { plugins: app.plugins, props: { companyId: 1 } });
  mounted.push(wrapper);
  await flushPromises();
  return wrapper;
}

describe("Overview widgets from other modules", () => {
  it("Sales yesterday: the trend ends yesterday, with its first and last day under it", async () => {
    // Today's point stays empty until a shift closes (Z-report): it is not a day of zero sales.
    const series = Array.from({ length: 14 }, (_, i) => ({ date: `2026-10-${String(8 + i).padStart(2, "0")}`, net: i === 13 ? null : String(15_000_000 + i * 100_000), receipts: i === 13 ? null : 300 }));
    stub({ "sales/summary/": () => json({ range: { from: "2026-10-08", to: "2026-10-21" }, compare: null, totals: {}, series, breakdown: [] }) });
    const wrapper = await mountWidget(SalesTodayWidget);
    const tile = wrapper.findComponent(KpiCard);
    expect(tile.props("value")).toBe("16200000");
    expect(tile.props("spark")).toHaveLength(13);
    expect(tile.props("spark")!.at(-1)).toBe("16200000");
    expect(tile.props("sparkLabels")).toEqual(["8 Oct", "Yesterday"]);
  });

  it("Present now says the rostered count once", async () => {
    mergeModuleMessages("attendance", { en: attendanceEn });
    stub({
      "attendance/board/": () =>
        json({ date: "2026-10-21", is_today: true, now: "2026-10-21T12:00:00Z", holiday: null, totals: { in: 8, late: 1, not_yet: 1, absent: 0, off: 6, rostered: 10, late_missing: 0 }, branches: [], people: [] }),
      "attendance/summary/": () => json({ series: [] }),
    });
    const wrapper = await mountWidget(PresentWidget);
    expect(wrapper.text()).toContain("of 10 on shift");
    expect(wrapper.text()).not.toContain("/ 10");
    expect(wrapper.text()).toContain("90%");
  });
});
