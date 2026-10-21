// The registry first, as in the app (core/modules loads every module's index.ts).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import { confirmQueue, settleConfirm } from "@/components/useConfirm";
import { mergeModuleMessages } from "@/i18n";
import { company, json, me } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";
import { useSessionStore } from "@/stores/session";

import NewCompanyForm from "../components/NewCompanyForm.vue";
import SetupPill from "../components/SetupPill.vue";
import en from "../i18n/en.json";
import ru from "../i18n/ru.json";
import uz from "../i18n/uz.json";
import GetStartedPage from "../pages/GetStartedPage.vue";
import type { NewCompanyInfo, Setup } from "../types";

mergeModuleMessages("setup", { en, ru, uz });

interface Call {
  method: string;
  url: string;
  body: unknown;
}

function stub(routes: Record<string, (call: Call) => Response>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const call = { method: init?.method ?? "GET", url, body: init?.body ? JSON.parse(String(init.body)) : undefined };
      calls.push(call);
      const path = url.replace("/api/v1/owner/companies/1/", "").replace("/api/v1", "").split("?")[0]!;
      const handler = routes[`${call.method} ${path}`];
      return handler ? handler(call) : json({ detail: "Not found." }, 404);
    }),
  );
  return calls;
}

const SETUP: Setup = {
  steps: [
    { key: "companies.branches", label: "Set up your branches", description: "x", url: "settings/branches", order: 10, done: true },
    { key: "companies.invite", label: "Invite your staff", description: "x", url: "settings/invite", order: 20, done: false },
    { key: "groups.connect", label: "Connect a Telegram group", description: "x", url: "groups", order: 30, done: false },
    { key: "finance.opening", label: "Opening balances", description: "Money you start with.", url: "finance/accounts", order: 60, done: false },
  ],
  done: 1,
  total: 4,
  dismissed: false,
  can_dismiss: true,
};

afterEach(() => {
  vi.unstubAllGlobals();
  confirmQueue.value = [];
});

describe("GetStartedPage", () => {
  it("lists the steps with progress, marks the next one and links each to its page", async () => {
    stub({ "GET setup/": () => json(SETUP) });
    const app = await testApp("/c/1/get-started");
    const { wrapper } = mountWithProviders(GetStartedPage, { plugins: app.plugins });
    await flushPromises();

    expect(wrapper.text()).toContain("1 of 4 steps done");
    expect(wrapper.text()).toContain("25%");
    const items = wrapper.findAll("li");
    expect(items).toHaveLength(4);
    // The next step is the first one not done; module steps keep their server label.
    expect(items[1]!.text()).toContain("Next");
    expect(items[3]!.text()).toContain("Opening balances");
    expect(items[3]!.text()).toContain("Money you start with.");
    const links = wrapper.findAll("a").map((a) => a.attributes("href"));
    expect(links).toContain("/c/1/settings/invite");
    expect(links).toContain("/c/1/finance/accounts");
  });

  it("dismisses after asking, and celebrates when everything is done", async () => {
    const calls = stub({
      "GET setup/": () => json(SETUP),
      "POST setup/dismiss/": () => json({ ...SETUP, dismissed: true }),
      "GET /owner/me/": () => json(me()),
    });
    const app = await testApp("/c/1/get-started");
    const { wrapper } = mountWithProviders(GetStartedPage, { plugins: app.plugins });
    await flushPromises();

    await wrapper.findAll("button").find((b) => b.text() === "Dismiss for now")!.trigger("click");
    await flushPromises();
    settleConfirm(confirmQueue.value[0]!.id, { reason: "" }, 0);
    await flushPromises();
    expect(calls.some((c) => c.method === "POST" && c.url.endsWith("setup/dismiss/"))).toBe(true);
    expect(wrapper.text()).toContain("Show in the sidebar");

    stub({ "GET setup/": () => json({ ...SETUP, done: 4, steps: SETUP.steps.map((s) => ({ ...s, done: true })) }) });
    const again = mountWithProviders(GetStartedPage, { plugins: (await testApp("/c/1/get-started")).plugins });
    await flushPromises();
    expect(again.wrapper.text()).toContain("You’re all set");
    // All done and still shown: the card offers to hide it; nothing offers to "show" it again.
    expect(again.wrapper.text()).toContain("Hide the checklist");
    expect(again.wrapper.text()).not.toContain("Show in the sidebar");
    expect(again.wrapper.text()).not.toContain("Dismiss for now");
  });
});

describe("SetupPill", () => {
  it("shows progress until the checklist is complete or dismissed", async () => {
    stub({ "GET setup/": () => json(SETUP) });
    const app = await testApp("/c/1");
    useSessionStore().me = me([company({ setup_completed: false })]);
    const { wrapper } = mountWithProviders(SetupPill, { plugins: app.plugins });
    await flushPromises();
    expect(wrapper.text()).toContain("1/4");

    stub({ "GET setup/": () => json(SETUP) });
    const done = await testApp("/c/1");
    useSessionStore().me = me([company({ setup_completed: true })]);
    const hidden = mountWithProviders(SetupPill, { plugins: done.plugins });
    await flushPromises();
    expect(hidden.wrapper.text()).toBe("");
  });
});

describe("NewCompanyForm", () => {
  const info: NewCompanyInfo = {
    mode: "code",
    allowed: true,
    needs_code: true,
    reason: "",
    owned: 1,
    limit: 10,
    parts: [
      { key: "companies.settings", label: "Working days, report times and staff settings" },
      { key: "companies.modules", label: "Modules switched on" },
    ],
    sources: [{ id: 1, name: "Demo Dorixona", parts: ["companies.settings", "companies.modules"] }],
  };

  it("asks for a code when needed, copies the chosen setup and opens Get started", async () => {
    const close = vi.fn();
    const calls = stub({
      "GET /owner/companies/new/": () => json(info),
      "POST /owner/companies/": () => json({ id: 9, name: "Bodomgul Dorixonasi", slug: "bodomgul-dorixonasi", copied: { "companies.settings": 1 } }, 201),
      "GET /owner/me/": () => json(me([company(), company({ id: 9, name: "Bodomgul Dorixonasi" })])),
    });
    const app = await testApp("/c/1");
    const { wrapper } = mountWithProviders(NewCompanyForm, { props: { context: { close } }, plugins: app.plugins });
    await flushPromises();

    expect(wrapper.text()).toContain("Signup code");
    await wrapper.find('input[maxlength="200"]').setValue("Bodomgul Dorixonasi");
    await wrapper.find("form").trigger("submit");
    await flushPromises();
    expect(wrapper.text()).toContain("Enter the signup code you were given.");
    expect(calls.some((c) => c.method === "POST")).toBe(false);

    await wrapper.find('input[maxlength="32"]').setValue("k7m2-qx9p");
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toMatchObject({ name: "Bodomgul Dorixonasi", timezone: "Asia/Tashkent", base_currency: "UZS", signup_code: "k7m2-qx9p", copy_from: null, parts: [] });
    expect(close).toHaveBeenCalled();
    expect(app.router.currentRoute.value.fullPath).toBe("/c/9/get-started");
  });

  it("explains when creating isn't allowed", async () => {
    stub({ "GET /owner/companies/new/": () => json({ ...info, allowed: false, reason: "New companies are created by the platform team for now." }) });
    const app = await testApp("/c/1");
    const { wrapper } = mountWithProviders(NewCompanyForm, { plugins: app.plugins });
    await flushPromises();

    expect(wrapper.text()).toContain("created by the platform team");
    expect(wrapper.find("form").exists()).toBe(false);
  });
});
