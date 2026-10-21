// The Overview's "Present now" tile says the rostered count once.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import en from "../../i18n/en.json";
import PresentWidget from "../PresentWidget.vue";

afterEach(() => vi.unstubAllGlobals());

describe("PresentWidget", () => {
  it("says the rostered count once", async () => {
    mergeModuleMessages("attendance", { en });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string) => {
        const url = String(input);
        if (url.includes("/attendance/board/"))
          return json({ date: "2026-10-21", is_today: true, now: "2026-10-21T12:00:00Z", holiday: null, totals: { in: 8, late: 1, not_yet: 1, absent: 0, off: 6, rostered: 10, late_missing: 0 }, branches: [], people: [] });
        if (url.includes("/attendance/summary/")) return json({ series: [] });
        return json({ detail: "Not found." }, 404);
      }),
    );
    const app = await testApp("/c/1");
    const { wrapper } = mountWithProviders(PresentWidget, { plugins: app.plugins, props: { companyId: 1 } });
    await flushPromises();
    expect(wrapper.text()).toContain("of 10 on shift");
    expect(wrapper.text()).not.toContain("/ 10");
    expect(wrapper.text()).toContain("90%");
    wrapper.unmount();
  });
});
