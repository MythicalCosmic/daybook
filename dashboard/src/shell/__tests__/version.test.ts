// The registry first, as in the app.
import "@/core/modules";

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { flushPromises } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import MoreSheet from "../MoreSheet.vue";
import TopBar from "../TopBar.vue";

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("release", () => {
  it("is the version in package.json", () => {
    // Vitest runs in dashboard/; under jsdom import.meta.url isn't a file URL.
    const { version } = JSON.parse(readFileSync(resolve(process.cwd(), "package.json"), "utf8")) as { version: string };
    expect(__APP_VERSION__).toBe(version);
    expect(version).toMatch(/^\d+\.\d+\.\d+$/);
  });

  it("is the quiet last line of the phone More sheet, under Log out", async () => {
    const app = await testApp("/c/1", "uz");
    const { wrapper } = mountWithProviders(MoreSheet, { plugins: app.plugins, props: { open: true, groups: [] } });
    await flushPromises();
    const line = document.querySelector("[data-version]");
    expect(line?.textContent?.trim()).toBe(`Versiya ${__APP_VERSION__}`);
    const text = document.body.textContent ?? "";
    expect(text.indexOf("Versiya")).toBeGreaterThan(text.indexOf("Chiqish"));
    wrapper.unmount();
  });

  it("ends the desktop account menu", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ results: [] })));
    const app = await testApp("/c/1", "ru");
    const { wrapper } = mountWithProviders(TopBar, {
      plugins: app.plugins,
      props: { phone: false, companyless: false, aiAvailable: false, inboxCount: 0, inboxCritical: false },
    });
    await flushPromises();
    await wrapper.find('button[aria-label="Аккаунт"]').trigger("click");
    await flushPromises();
    const menu = document.querySelector("[role=menu]");
    expect(menu?.textContent).toContain(`Версия ${__APP_VERSION__}`);
    wrapper.unmount();
  });
});
