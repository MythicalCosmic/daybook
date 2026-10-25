// One company everywhere: a company picked in the switcher moves the bot too (the owner's `me`
// takes `bot_company`); opening a link to another company's page doesn't.
import { flushPromises } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";

import { useCompanyStore } from "@/stores/company";
import { useSessionStore } from "@/stores/session";
import { company, json, manager, me } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import { useCompanySwitcher } from "../companySwitcher";

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

function stubFetch() {
  const calls: Array<{ method: string; url: string; body: unknown }> = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ method: init?.method ?? "GET", url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      return json({});
    }),
  );
  return calls;
}

describe("one company everywhere", () => {
  it("saves the company picked in the switcher as the bot's company", async () => {
    const calls = stubFetch();
    const app = await testApp("/c/1/tasks");
    useSessionStore().me = me([company(), manager([])]);
    let switcher: ReturnType<typeof useCompanySwitcher> | null = null;
    const Probe = defineComponent({
      setup() {
        switcher = useCompanySwitcher();
        return () => h("div");
      },
    });
    const { wrapper } = mountWithProviders(Probe, { plugins: app.plugins });
    switcher!.openCompany(2);
    await flushPromises();
    expect(app.router.currentRoute.value.path.startsWith("/c/2")).toBe(true);
    expect(calls.filter((call) => call.method === "PATCH")).toEqual([{ method: "PATCH", url: "/api/v1/owner/me/", body: { bot_company: 2 } }]);
    // "/" in this tab opens the company just picked, not the one picked before the page loaded.
    expect(useSessionStore().me?.bot_company).toBe(2);
    expect(useCompanyStore().defaultCompanyId()).toBe(2);

    // The company already open (the app's router guard sets it from the URL): nothing to move.
    useCompanyStore().setCurrent(2);
    switcher!.openCompany(2);
    await flushPromises();
    expect(calls.filter((call) => call.method === "PATCH")).toHaveLength(1);
    wrapper.unmount();
  });

  it("leaves the bot alone when a link opens another company's page", async () => {
    const calls = stubFetch();
    const app = await testApp("/c/1/tasks");
    useSessionStore().me = me([company(), manager([])]);
    await app.router.push("/c/2/tasks?task=41");
    await flushPromises();
    expect(calls.filter((call) => call.method === "PATCH")).toEqual([]);
  });
});
