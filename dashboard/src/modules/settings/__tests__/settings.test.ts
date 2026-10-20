// The registry first, as in the app (core/modules loads every module's index.ts).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import { confirmQueue, settleConfirm } from "@/components/useConfirm";
import { mergeModuleMessages } from "@/i18n";
import { company, json, me } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";
import { useSessionStore } from "@/stores/session";

import { createBranch, listSessions, putPreferences, reorderBranches, revokeAllSessions, setFeatures, uploadLogo } from "../api";
import en from "../i18n/en.json";
import ru from "../i18n/ru.json";
import uz from "../i18n/uz.json";
import CompanyPanel from "../panels/CompanyPanel.vue";
import FeaturesPanel from "../panels/FeaturesPanel.vue";
import type { CompanySettings, Features } from "../types";

mergeModuleMessages("settings", { en, ru, uz });

interface Call {
  method: string;
  url: string;
  body: unknown;
}

function stub(routes: Record<string, (call: Call) => Response | Promise<Response>>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const body = init?.body instanceof FormData ? init.body : init?.body ? JSON.parse(String(init.body)) : undefined;
      const call = { method: init?.method ?? "GET", url, body };
      calls.push(call);
      const path = url.replace("/api/v1/owner/companies/1/", "").replace("/api/v1", "").split("?")[0]!;
      const handler = routes[`${call.method} ${path}`];
      return handler ? handler(call) : json({ detail: "Not found." }, 404);
    }),
  );
  return calls;
}

const SETTINGS: CompanySettings = {
  id: 1,
  name: "Demo Shop",
  slug: "demo-shop",
  logo: null,
  timezone: "Asia/Tashkent",
  default_language: "uz",
  base_currency: "UZS",
  base_currency_locked: true,
  workdays: [0, 1, 2, 3, 4, 5],
  morning_report_at: "09:00",
  evening_report_at: "20:00",
  morning_digest: true,
  rejoin_cooldown_hours: 24,
  owner_sees_personal_tasks: true,
  team_directory_phones: true,
  features: ["finance"],
  setup_completed: false,
};

const FEATURES: Features = {
  features: ["finance"],
  modules: (["finance", "sales", "stock", "attendance", "hr", "payroll", "ai", "recognition"] as const).map((key) => ({ key, label: key, enabled: key === "finance" })),
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  confirmQueue.value = [];
});

describe("api", () => {
  it("calls the company setup endpoints", async () => {
    const calls = stub({
      "PATCH features/": () => json(FEATURES),
      "POST branches/": () => json({ id: 3 }, 201),
      "POST branches/reorder/": () => json([]),
      "PUT notification-preferences/": () => json([]),
      "POST settings/logo/": () => json(SETTINGS),
      "GET /owner/auth/sessions/": () => json([]),
      "POST /owner/auth/sessions/revoke-all/": () => json({ revoked: 2, signed_out: false }),
    });
    await setFeatures(1, ["finance", "sales"]);
    await createBranch(1, { name: "Yunusobod", geofence_m: 120 });
    await reorderBranches(1, [2, 1]);
    await putPreferences(1, [{ kind: "inbox.system", in_app: true, telegram: false }]);
    await uploadLogo(1, new File(["x"], "logo.png", { type: "image/png" }));
    await listSessions();
    await revokeAllSessions(true);

    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
      "PATCH /api/v1/owner/companies/1/features/",
      "POST /api/v1/owner/companies/1/branches/",
      "POST /api/v1/owner/companies/1/branches/reorder/",
      "PUT /api/v1/owner/companies/1/notification-preferences/",
      "POST /api/v1/owner/companies/1/settings/logo/",
      "GET /api/v1/owner/auth/sessions/",
      "POST /api/v1/owner/auth/sessions/revoke-all/",
    ]);
    expect(calls[0]!.body).toEqual({ features: ["finance", "sales"] });
    expect(calls[4]!.body).toBeInstanceOf(FormData);
    expect(calls[6]!.body).toEqual({ keep_current: true });
  });
});

describe("CompanyPanel", () => {
  it("saves only after a change, sends the form and reloads me", async () => {
    const calls = stub({
      "GET settings/": () => json(SETTINGS),
      "PATCH settings/": (call) => json({ ...SETTINGS, ...(call.body as object) }),
      "GET /owner/me/": () => json(me()),
    });
    const app = await testApp("/c/1/settings/company");
    const { wrapper } = mountWithProviders(CompanyPanel, { plugins: app.plugins });
    await flushPromises();

    expect(wrapper.text()).toContain("Identity");
    // Locked currency: the money is already booked.
    expect(wrapper.text()).toContain("Locked: money is already booked in it.");
    expect(wrapper.text()).not.toContain("Unsaved changes");

    await wrapper.find('input[maxlength="200"]').setValue("Baraka Market");
    await flushPromises();
    expect(document.body.textContent).toContain("Discard");
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    const patch = calls.find((c) => c.method === "PATCH");
    expect(patch?.body).toMatchObject({ name: "Baraka Market", workdays: [0, 1, 2, 3, 4, 5], morning_report_at: "09:00" });
    expect(calls.some((c) => c.url.endsWith("/owner/me/"))).toBe(true);
  });

  it("is read-only without company.settings", async () => {
    stub({ "GET settings/": () => json(SETTINGS) });
    const app = await testApp("/c/1/settings/company");
    useSessionStore().me = me([company({ is_owner: false, permissions: ["dashboard.access"], role: { id: 2, name: "Manager" } })]);
    const { wrapper } = mountWithProviders(CompanyPanel, { plugins: app.plugins });
    await flushPromises();

    expect(wrapper.text()).toContain("View only");
    expect((wrapper.find('input[maxlength="200"]').element as HTMLInputElement).disabled).toBe(true);
    expect(wrapper.text()).not.toContain("Upload logo");
  });
});

const BRANCH = {
  id: 7,
  name: "Chilonzor",
  code: "CHL",
  address: "Bunyodkor 12",
  phone: "",
  latitude: "41.285480",
  longitude: "69.203560",
  geofence_m: 150,
  opens_at: "09:00",
  closes_at: "21:00",
  open_weekdays: [0, 1, 2, 3, 4, 5, 6],
  manager: { id: 4, name: "Bekzod Mirzayev" },
  cash_limit: "20000000.00",
  is_active: true,
  order: 1,
  people: 4,
};

describe("BranchesPanel", () => {
  it("lists branches and says so when a link points at a branch that isn't there", async () => {
    stub({ "GET branches/": () => json([BRANCH]), "GET branches/managers/": () => json([]) });
    const app = await testApp("/c/1/settings/branches?branch=999");
    const { default: BranchesPanel } = await import("../panels/BranchesPanel.vue");
    const { wrapper } = mountWithProviders(BranchesPanel, { plugins: app.plugins });
    await flushPromises();

    expect(wrapper.text()).toContain("Chilonzor");
    expect(wrapper.text()).toContain("Bekzod Mirzayev");
    expect(document.body.textContent).toContain("This branch isn’t here");
    // Nothing to save in that state.
    expect([...document.querySelectorAll("button")].some((b) => b.textContent?.trim() === "Save")).toBe(false);
    wrapper.unmount();
  });
});

describe("FeaturesPanel", () => {
  it("switches a module on at once and puts it back when the server refuses", async () => {
    let refuse = false;
    const calls = stub({
      "GET features/": () => json(FEATURES),
      "PATCH features/": (call) =>
        refuse ? json({ detail: "No" }, 400) : json({ features: (call.body as { features: string[] }).features, modules: FEATURES.modules.map((m) => ({ ...m, enabled: (call.body as { features: string[] }).features.includes(m.key) })) }),
      "GET /owner/me/": () => json(me()),
    });
    const app = await testApp("/c/1/settings/features");
    const { wrapper } = mountWithProviders(FeaturesPanel, { plugins: app.plugins });
    await flushPromises();
    expect(wrapper.text()).toContain("1 of 8 on");

    const switches = wrapper.findAll('[role="switch"]');
    expect(switches).toHaveLength(8);
    await switches[1]!.trigger("click"); // Sales on
    await flushPromises();
    expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ features: ["finance", "sales"] });
    expect(wrapper.text()).toContain("2 of 8 on");

    // Switching off asks first, then rolls back when refused.
    refuse = true;
    await wrapper.findAll('[role="switch"]')[1]!.trigger("click");
    await flushPromises();
    expect(confirmQueue.value).toHaveLength(1);
    settleConfirm(confirmQueue.value[0]!.id, { reason: "" }, 0);
    await flushPromises();
    expect(wrapper.text()).toContain("2 of 8 on");
    expect(wrapper.findAll('[role="switch"]')[1]!.attributes("data-state")).toBe("checked");
  });
});
