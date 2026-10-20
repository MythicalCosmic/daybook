// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { toasts } from "@/components/useToast";
import { mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import { routineKeys, routinesApi } from "../api";
import RoutineEditor from "../components/RoutineEditor.vue";
import en from "../i18n/en.json";
import module from "../index";
import type { Routine } from "../types";

interface Call {
  method: string;
  url: string;
  body: unknown;
}

function stub(routes: Record<string, (call: Call) => Response>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const call = { method: init?.method ?? "GET", url: input, body: init?.body ? JSON.parse(String(init.body)) : undefined };
      calls.push(call);
      const path = input.replace("/api/v1/owner/companies/1/", "").split("?")[0]!;
      return routes[`${call.method} ${path}`]?.(call) ?? json({ detail: "Not found." }, 404);
    }),
  );
  return calls;
}

const routine = (overrides: Partial<Routine> = {}): Routine => ({
  id: 32,
  title: "Open the shop: checklist",
  description: "",
  weekdays: [0, 1, 2, 3, 4],
  due_time: "08:45:00",
  starts_on: null,
  is_active: true,
  onboarding: false,
  due_after_days: 1,
  proof: "photo",
  needs_confirmation: true,
  checklist: ["Lights on", "Count the till"],
  branch: { id: 1, name: "Chilonzor", code: "CHL" },
  assignees: [{ id: 11, name: "Alisher Valiyev", photo_url: null, position: "Sales floor" }],
  positions: [],
  reminder_policy: null,
  escalate_to: null,
  stats: null,
  created_at: "2026-09-01T08:00:00Z",
  ...overrides,
});

const options = { people: [{ id: 11, name: "Alisher Valiyev", photo_url: null, position: "Sales floor", branch: "Chilonzor", branch_id: 1, position_id: 3 }], positions: [], routines: [], policies: [] };

beforeEach(() => {
  mergeModuleMessages("routines", { en, ru: en, uz: en });
  toasts.splice(0, toasts.length);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

describe("api", () => {
  it("lists, previews and measures routines through the owner endpoints", async () => {
    const calls = stub({
      "GET routines/": () => json([]),
      "GET routines/32/preview/": () => json({ day: "2026-10-22", due: true, holiday: false, people: [] }),
      "GET routines/32/compliance/": () => json({ totals: {}, series: [], people: [] }),
      "POST routines/": () => json(routine(), 201),
      "PATCH routines/32/": () => json(routine()),
      "DELETE routines/32/": () => new Response(null, { status: 204 }),
    });
    await routinesApi.list(1, { onboarding: true, q: "kassa" });
    await routinesApi.list(1, { active: false });
    await routinesApi.preview(1, 32, "2026-10-22");
    await routinesApi.compliance(1, 32, { from: "2026-09-22", to: "2026-10-21" });
    await routinesApi.create(1, { title: "Count the till", weekdays: [0], due_time: "21:00", assignee_ids: [11] });
    await routinesApi.update(1, 32, { is_active: false });
    await routinesApi.remove(1, 32);
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
      "GET /api/v1/owner/companies/1/routines/?onboarding=true&q=kassa",
      "GET /api/v1/owner/companies/1/routines/?active=false",
      "GET /api/v1/owner/companies/1/routines/32/preview/?day=2026-10-22",
      "GET /api/v1/owner/companies/1/routines/32/compliance/?from=2026-09-22&to=2026-10-21",
      "POST /api/v1/owner/companies/1/routines/",
      "PATCH /api/v1/owner/companies/1/routines/32/",
      "DELETE /api/v1/owner/companies/1/routines/32/",
    ]);
    expect(calls[5]!.body).toEqual({ is_active: false });
  });

  it("registers in Work behind tasks.templates", () => {
    expect(module).toMatchObject({ id: "routines", group: "work", order: 30, perm: "tasks.templates" });
    expect(routineKeys.preview(1, 32, "2026-10-22")).toEqual([1, "routines", "preview", { id: 32, day: "2026-10-22" }]);
  });

  it("the palette's New routine opens the editor, not just the list", () => {
    const go = vi.fn();
    const commands = module.commands!({ t: (key: string) => key, go, can: () => true } as never);
    commands.find((command) => command.id === "routines.new")!.run();
    expect(go).toHaveBeenCalledWith("routines?new=1");
  });
});

describe("RoutinesPage", () => {
  it("opens a new routine from ?new=1 and drops the flag from the URL", async () => {
    stub({ "GET routines/": () => json([routine()]), "GET tasks/options/": () => json(options) });
    const app = await testApp("/c/1/routines?new=1");
    // The page links to its tabs and to a routine by route name.
    for (const name of ["routines.list", "routines.onboarding", "routines.detail"]) {
      app.router.addRoute({ path: `/named/${name}/:id?`, name, component: { render: () => null } });
    }
    const { default: RoutinesPage } = await import("../pages/RoutinesPage.vue");
    const { wrapper } = mountWithProviders(RoutinesPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    expect(document.body.querySelector("[role=dialog]")?.textContent).toContain("New routine");
    expect(app.router.currentRoute.value.query.new).toBeUndefined();
    wrapper.unmount();
  });
});

describe("RoutineEditor", () => {
  it("won't create a routine nobody gets", async () => {
    const calls = stub({ "GET tasks/options/": () => json(options) });
    const app = await testApp("/c/1/routines");
    const { wrapper } = mountWithProviders(RoutineEditor, { plugins: app.plugins, props: { open: true } });
    await flushPromises();
    const title = document.body.querySelector<HTMLInputElement>("input[type=text], input:not([type])");
    title!.value = "Wipe the windows";
    title!.dispatchEvent(new Event("input"));
    [...document.body.querySelectorAll("button")].find((b) => b.textContent?.trim() === "Create")!.click();
    await flushPromises();
    expect(document.body.textContent).toContain("Pick people or positions");
    expect(calls.some((c) => c.method === "POST")).toBe(false);
    wrapper.unmount();
  });

  it("saves an edited routine with its days, time, people and checklist", async () => {
    const calls = stub({
      "GET tasks/options/": () => json(options),
      "GET routines/32/preview/": () => json({ day: "2026-10-22", due: true, holiday: false, people: [] }),
      "PATCH routines/32/": (call) => json(routine({ ...(call.body as object) })),
    });
    const app = await testApp("/c/1/routines/32");
    const { wrapper } = mountWithProviders(RoutineEditor, { plugins: app.plugins, props: { open: true, routine: routine() } });
    await flushPromises();
    [...document.body.querySelectorAll("button")].find((b) => b.textContent?.trim() === "Save")!.click();
    await flushPromises();
    const patch = calls.find((c) => c.method === "PATCH");
    expect(patch?.body).toMatchObject({
      title: "Open the shop: checklist",
      weekdays: [0, 1, 2, 3, 4],
      due_time: "08:45",
      assignee_ids: [11],
      position_ids: [],
      branch_id: 1,
      proof: "photo",
      needs_confirmation: true,
      checklist: ["Lights on", "Count the till"],
      is_active: true,
    });
    expect(patch?.body).not.toHaveProperty("onboarding");
    expect(toasts.at(-1)?.title).toBe("Saved");
    wrapper.unmount();
  });

  it("sends onboarding tasks as a day after approval instead of weekdays", async () => {
    const calls = stub({
      "GET tasks/options/": () => json(options),
      "GET routines/40/preview/": () => json({ day: "2026-10-22", due: false, holiday: false, people: [] }),
      "PATCH routines/40/": (call) => json(routine({ id: 40, onboarding: true, ...(call.body as object) })),
    });
    const app = await testApp("/c/1/routines/onboarding");
    const onboarding = routine({ id: 40, onboarding: true, due_after_days: 3, title: "Meet your manager", assignees: [], checklist: [] });
    const { wrapper } = mountWithProviders(RoutineEditor, { plugins: app.plugins, props: { open: true, routine: onboarding } });
    await flushPromises();
    [...document.body.querySelectorAll("button")].find((b) => b.textContent?.trim() === "Save")!.click();
    await flushPromises();
    const patch = calls.find((c) => c.method === "PATCH");
    expect(patch?.body).toMatchObject({ onboarding: true, due_after_days: 3 });
    expect(patch?.body).not.toHaveProperty("weekdays");
    wrapper.unmount();
  });
});
