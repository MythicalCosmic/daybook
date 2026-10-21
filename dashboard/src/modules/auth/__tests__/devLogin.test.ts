// The registry first, as in the app (core/modules loads every module's index.ts).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mergeModuleMessages } from "@/i18n";
import { json, me } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import { DEMO_COMPANIES, DEMO_STRANGERS } from "../demoPeople";
import en from "../i18n/en.json";
import ru from "../i18n/ru.json";
import uz from "../i18n/uz.json";
import DevLoginPage from "../pages/DevLoginPage.vue";

const everyone = [...DEMO_COMPANIES.flatMap((company) => company.people), ...DEMO_STRANGERS];

afterEach(() => vi.unstubAllGlobals());

describe("development sign-in", () => {
  it("offers only the demo people, by demo company", () => {
    expect(DEMO_COMPANIES.map((company) => company.name)).toEqual(["Demo Dorixona", "Demo Distribyutor"]);
    // As `make demo` prints them (backend/apps/core/demo_plan.py PEOPLE and SMALL_PEOPLE).
    expect(everyone.map((person) => person.id)).toEqual([1001, 1002, 4242, 1004, 1005, 1006, 2001, 2002, 2003, 5001, 5002, 5003]);
    // Demo ids are short; a real Telegram id (nine or ten digits) never goes in the repository.
    for (const person of everyone) expect(String(person.id)).toMatch(/^\d{4}$/);
  });

  it("names every person's role in all three languages", () => {
    for (const dictionary of [en, uz, ru] as Array<Record<string, string>>) {
      for (const person of everyone) expect(dictionary[person.role], person.role).toBeTruthy();
      expect(dictionary["auth.dev.strangers"]).toBeTruthy();
    }
  });

  it("signs in as the person picked", async () => {
    const calls: Array<{ url: string; body: unknown }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : null });
        if (url.endsWith("/auth/dev-login/")) return json({ access: "dev-access" });
        return json(me());
      }),
    );
    const app = await testApp("/dev/login");
    mergeModuleMessages("auth", { en });
    const { wrapper } = mountWithProviders(DevLoginPage, { plugins: app.plugins });
    await flushPromises();

    expect(wrapper.findAll("[data-demo-company] h2").map((heading) => heading.text())).toEqual(["Demo Dorixona", "Demo Distribyutor"]);
    expect(wrapper.text()).toContain("Head of pharmacy · 1002");
    expect(wrapper.text()).not.toContain("auth.dev.");

    await wrapper.get('[data-telegram-id="2001"]').trigger("click");
    await flushPromises();
    const login = calls.find((call) => call.url.endsWith("/auth/dev-login/"));
    expect(login?.body).toEqual({ telegram_id: 2001 });
    wrapper.unmount();
  });
});
