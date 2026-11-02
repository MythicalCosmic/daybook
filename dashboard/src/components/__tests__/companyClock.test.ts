/**
 * Shared date pieces take "today" from the company's clock (useCompanyToday), so a console left
 * open past midnight moves on to the new day. Its own file: the clock is one shared interval, and a
 * component another test left mounted would keep a real one running.
 */
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";

import CalendarMonth from "@/components/CalendarMonth.vue";
import { i18n, setLanguage } from "@/i18n";
import { useCompanyStore } from "@/stores/company";
import { useSessionStore } from "@/stores/session";
import { me } from "@/test/fixtures";

afterEach(() => vi.useRealTimers());

describe("the company's today", () => {
  it("CalendarMonth moves its today mark at the company's midnight while it stays open", async () => {
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
    // 23:59:50 in Tashkent.
    vi.setSystemTime(new Date("2026-11-02T18:59:50Z"));
    const pinia = createPinia();
    setActivePinia(pinia);
    useSessionStore().me = me();
    useCompanyStore().setCurrent(1);
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/:any(.*)*", component: { render: () => null } }] });
    setLanguage("en");
    const month = mount(CalendarMonth, { props: { items: [], month: "2026-11" }, global: { plugins: [pinia, router, i18n] } });
    expect(month.find("[aria-current=date]").attributes("data-day")).toBe("2026-11-02");
    vi.advanceTimersByTime(30_000);
    await nextTick();
    expect(month.find("[aria-current=date]").attributes("data-day")).toBe("2026-11-03");
    month.unmount();
  });
});
