// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { toasts } from "@/components/useToast";
import { mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import { routineKeys, routinesApi } from "../api";
import { formatRoutineAudit, routineFieldLabels } from "../audit";
import RoutineEditor from "../components/RoutineEditor.vue";
import en from "../i18n/en.json";
import module from "../index";
import { afterSave, missesToday, nextRunOf, runDayWords, runLabel, type RunWords } from "../lib";
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
  next_run: null,
  today: null,
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

describe("history", () => {
  it("reads raw audit values back as names and words", () => {
    const t = (key: string) => (en as Record<string, string>)[key] ?? key;
    const format = formatRoutineAudit(t, { options: { ...options, positions: [{ id: 3, name: "Cashier" }], policies: [{ id: 24, name: "Strict", is_default: false }] }, branches: [{ id: 18, name: "Chilonzor" }] });
    expect(format("branch", 18)).toBe("Chilonzor");
    expect(format("escalate_to", 11)).toBe("Alisher Valiyev");
    expect(format("reminder_policy", 24)).toBe("Strict");
    expect(format("assignees", [11, 99])).toBe("Alisher Valiyev, #99");
    expect(format("positions", [3])).toBe("Cashier");
    expect(format("weekdays", [0, 5])).toBe("Mon, Sat");
    expect(format("proof", "photo")).toBe("Photo");
    expect(format("due_time", "08:30:00")).toBe("08:30");
    expect(format("branch", null)).toBeNull();
    expect(format("title", "Count the till")).toBeNull(); // AuditTrail shows plain text itself
    expect(routineFieldLabels(t).escalate_to).toBe("Who hears when it's late");
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

describe("next run", () => {
  const TZ = "Asia/Tashkent";
  // Wednesday 21 October 2026, 12:30 in Tashkent (UTC+5).
  const NOW = Date.parse("2026-10-21T07:30:00Z");
  const every = [0, 1, 2, 3, 4, 5, 6];
  const clock = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  const words: RunWords = {
    t: (key, params) => `${key}${params ? JSON.stringify(params) : ""}`,
    timeZone: TZ,
    now: NOW,
    time: (iso) => clock.format(new Date(iso)),
    day: (day) => day,
  };

  it("is the first of its days whose time is still ahead, like the generator", () => {
    expect(nextRunOf({ weekdays: every, due_time: "13:00", starts_on: null }, NOW, TZ)).toBe("2026-10-21T08:00:00.000Z");
    expect(nextRunOf({ weekdays: every, due_time: "09:00", starts_on: null }, NOW, TZ)).toBe("2026-10-22T04:00:00.000Z");
    expect(nextRunOf({ weekdays: [0], due_time: "09:00:00", starts_on: null }, NOW, TZ)).toBe("2026-10-26T04:00:00.000Z");
    expect(nextRunOf({ weekdays: every, due_time: "09:00", starts_on: "2026-11-02" }, NOW, TZ)).toBe("2026-11-02T04:00:00.000Z");
    expect(nextRunOf({ weekdays: every, due_time: "09:00", starts_on: null, is_active: false }, NOW, TZ)).toBeNull();
    expect(nextRunOf({ weekdays: [], due_time: "09:00", starts_on: null }, NOW, TZ)).toBeNull();
  });

  it("knows a routine made now has missed today's deadline", () => {
    expect(missesToday({ weekdays: every, due_time: "09:00", starts_on: null }, NOW, TZ)).toBe(true);
    expect(missesToday({ weekdays: every, due_time: "13:00", starts_on: null }, NOW, TZ)).toBe(false);
    expect(missesToday({ weekdays: [0], due_time: "09:00", starts_on: null }, NOW, TZ)).toBe(false);
    expect(missesToday({ weekdays: every, due_time: "09:00", starts_on: "2026-10-25" }, NOW, TZ)).toBe(false);
  });

  it("says today, tomorrow, the weekday this week, else the date", () => {
    expect(runLabel("2026-10-21T08:00:00Z", words)).toBe('routines.run.today{"time":"13:00"}');
    expect(runLabel("2026-10-22T04:00:00Z", words)).toBe('routines.run.tomorrow{"time":"09:00"}');
    expect(runLabel("2026-10-26T04:00:00Z", words)).toBe('routines.run.weekday{"day":"routines.weekday.0","time":"09:00"}');
    expect(runLabel("2026-11-02T04:00:00Z", words)).toBe('routines.run.date{"day":"2026-11-02","time":"09:00"}');
    expect(runDayWords("2026-10-22T04:00:00Z", words)).toBe("routines.runDay.tomorrow");
    expect(runDayWords("2026-10-23T04:00:00Z", words)).toBe("routines.runDay.weekday.4");
  });

  it("opens the give-today dialog only for a new routine that missed today", () => {
    const late = { onboarding: false, today: { reason: "made_late", give: { people: 2, due_at: "2026-10-21T09:30:00Z" } } };
    expect(afterSave(late, true)).toBe("dialog");
    expect(afterSave(late, false)).toBe("offer");
    expect(afterSave({ onboarding: false, today: { reason: "made_late", give: null } }, false)).toBe("plain");
    expect(afterSave({ onboarding: false, today: { reason: null, give: null } }, true)).toBe("plain");
    expect(afterSave({ onboarding: true, today: null }, true)).toBe("plain");
  });
});

describe("a routine made after its time", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-21T07:30:00Z")); // Wednesday 12:30 in Tashkent
  });
  afterEach(() => vi.useRealTimers());

  it("the editor says its first tasks come tomorrow while it's being made", async () => {
    stub({ "GET tasks/options/": () => json(options) });
    const app = await testApp("/c/1/routines");
    const { wrapper } = mountWithProviders(RoutineEditor, { plugins: app.plugins, props: { open: true } });
    await flushPromises();
    const hint = document.body.querySelector("[data-testid=run-hint]")?.textContent ?? "";
    expect(hint).toContain("First tasks: Tomorrow 09:00");
    expect(hint).toContain("Today's 09:00 has already passed");
    wrapper.unmount();
  });

  it("says when it starts and gives today's task at the time picked", async () => {
    const calls = stub({
      "POST routines/50/give-today/": () => json({ given: 2, due_at: "2026-10-21T09:30:00Z", people: [] }, 201),
    });
    const made = routine({
      id: 50,
      title: "Muzlatgich haroratini yozish",
      weekdays: [0, 1, 2, 3, 4, 5, 6],
      due_time: "09:00:00",
      next_run: "2026-10-22T04:00:00Z",
      today: { date: "2026-10-21", reason: "made_late", give: { people: 2, due_at: "2026-10-21T09:30:00Z" } },
    });
    const app = await testApp("/c/1/routines");
    const { default: GiveTodayDialog } = await import("../components/GiveTodayDialog.vue");
    const { wrapper } = mountWithProviders(GiveTodayDialog, { plugins: app.plugins, props: { open: true, routine: made } });
    await flushPromises();
    const dialog = document.body.querySelector("[role=dialog]")?.textContent ?? "";
    expect(dialog).toContain("It starts tomorrow");
    expect(dialog).toContain("was made after today's 09:00, so its first tasks come tomorrow at 09:00");
    expect(dialog).toContain("2 people get it today");
    [...document.body.querySelectorAll("button")].find((b) => b.textContent?.trim() === "Give today's task now")!.click();
    await flushPromises();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ due_time: "14:30" });
    expect(toasts.at(-1)?.title).toBe("Today's task went to 2 people");
    wrapper.unmount();
  });

  it("gives today's task through give-today, with the time when one is picked", async () => {
    const calls = stub({ "POST routines/32/give-today/": () => json({ given: 1, due_at: "2026-10-21T09:30:00Z", people: [] }, 201) });
    await routinesApi.giveToday(1, 32, "14:30");
    await routinesApi.giveToday(1, 32, null);
    expect(calls.map((c) => [c.url, c.body])).toEqual([
      ["/api/v1/owner/companies/1/routines/32/give-today/", { due_time: "14:30" }],
      ["/api/v1/owner/companies/1/routines/32/give-today/", {}],
    ]);
  });
});
