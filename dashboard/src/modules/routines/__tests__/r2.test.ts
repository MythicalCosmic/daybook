// Round 2: the history heatmap's legend writes percentages the language's way.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import en from "../i18n/en.json";
import ru from "../i18n/ru.json";
import uz from "../i18n/uz.json";
import HistoryPage from "../pages/HistoryPage.vue";

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

const cell = { made: 1, finished: 1, on_time: 1, late: 0, missed: 0, open: 0, percent: 100 };

describe("HistoryPage legend", () => {
  it("says 100% in Uzbek (100 % is the Russian spacing)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string) => {
        if (String(input).includes("/routines/history/"))
          return json({
            range: { from: "2026-10-20", to: "2026-10-21" },
            days: ["2026-10-20", "2026-10-21"],
            routines: [{ routine: { id: 1, title: "Fridge 2–8 °C", due_time: "09:00", branch: null, proof: "photo", needs_confirmation: false, is_active: true }, cells: [cell, cell], totals: cell }],
            series: [],
            people: [],
            totals: cell,
          });
        return json({ people: [], positions: [], routines: [], policies: [] });
      }),
    );
    const app = await testApp("/c/1/routines/history", "uz");
    for (const name of ["routines.today", "routines.history", "routines.confirm", "routines.list", "routines.onboarding", "routines.detail"])
      app.router.addRoute({ path: `/named/${name}/:id?`, name, component: { render: () => null } });
    mergeModuleMessages("routines", { en, ru, uz });
    const { wrapper } = mountWithProviders(HistoryPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    const legend = document.body.querySelector("[data-testid=heatmap] header")!.textContent!;
    expect(legend).toContain("100%");
    expect(legend).not.toContain("100 %");
    wrapper.unmount();
  });
});
