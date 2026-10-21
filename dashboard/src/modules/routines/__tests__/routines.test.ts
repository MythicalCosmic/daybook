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
  title: "Open the pharmacy: checklist",
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

  it("registers in Work for whoever plans, sees or confirms routine work", () => {
    expect(module).toMatchObject({ id: "routines", group: "work", order: 30, perm: ["tasks.templates", "tasks.view_all", "tasks.confirm"] });
    // Today first (the home of routine work), then History, To confirm (with its badge) and the routines.
    expect(module.nav!.map((item) => [item.to, item.perm])).toEqual([
      ["routines", "tasks.view_all"],
      ["routines/history", "tasks.view_all"],
      ["routines/confirm", "tasks.confirm"],
      ["routines/all", "tasks.templates"],
    ]);
    expect(module.nav![2]!.badge!({ counters: { "tasks.routine_review": 4, "tasks.review": 9 }, versions: {} })).toBe(4);
    expect(routineKeys.preview(1, 32, "2026-10-22")).toEqual([1, "routines", "preview", { id: 32, day: "2026-10-22" }]);
  });

  it("the palette's New routine opens the editor, not just the list", () => {
    const go = vi.fn();
    const commands = module.commands!({ t: (key: string) => key, go, can: () => true } as never);
    commands.find((command) => command.id === "routines.new")!.run();
    expect(go).toHaveBeenCalledWith("routines/all?new=1");
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
    const app = await testApp("/c/1/routines/all?new=1");
    // The page links to its tabs and to a routine by route name.
    for (const name of ["routines.today", "routines.history", "routines.confirm", "routines.list", "routines.onboarding", "routines.detail"]) {
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
      title: "Open the pharmacy: checklist",
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

describe("routine work", () => {
  const PAGE_ROUTES = ["routines.today", "routines.history", "routines.confirm", "routines.list", "routines.onboarding", "routines.detail"];
  const ref = (id: number, title: string) => ({ id, title, due_time: "09:00", branch: { id: 1, name: "Chilonzor", code: "CHL" }, proof: "photo" as const, needs_confirmation: true, is_active: true });
  const run = (id: number, name: string, state: string, overrides: Record<string, unknown> = {}) => ({
    id,
    member: { id: id + 100, name, photo_url: null, position: "Farmatsevt" },
    branch: { id: 1, name: "Chilonzor", code: "CHL" },
    state,
    status: state === "review" ? "review" : state === "done" ? "done" : "todo",
    due_at: "2026-10-21T04:00:00Z",
    completed_at: null,
    on_time: null,
    proof: "photo",
    proof_text: "",
    proof_thumb: null,
    proof_photo: null,
    checklist: { done: 0, total: 0 },
    can_confirm: false,
    ...overrides,
  });
  const counts = { done: 1, review: 1, late: 1, missed: 0, returned: 0, open: 0, cancelled: 0, skipped: 1 };

  async function mountPage(path: string, file: "TodayPage" | "ConfirmPage" | "HistoryPage") {
    const app = await testApp(path);
    for (const name of PAGE_ROUTES) app.router.addRoute({ path: `/named/${name}/:id?`, name, component: { render: () => null } });
    const pages = { TodayPage: () => import("../pages/TodayPage.vue"), ConfirmPage: () => import("../pages/ConfirmPage.vue"), HistoryPage: () => import("../pages/HistoryPage.vue") };
    const { default: Page } = await pages[file]();
    const mounted = mountWithProviders(Page, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    return { app, ...mounted };
  }

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-21T07:30:00Z")); // Wednesday 12:30 in Tashkent
  });
  afterEach(() => vi.useRealTimers());

  it("reads a day, its history and what waits for confirmation, and confirms through the tasks bulk endpoint", async () => {
    const calls = stub({
      "GET routines/day/": () => json({ day: "2026-10-21", holiday: false, idle: 0, totals: {}, routines: [] }),
      "GET routines/history/": () => json({ range: {}, days: [], routines: [], series: [], people: [], totals: {} }),
      "GET routines/to-confirm/": () => json({ count: 0, groups: [] }),
      "POST tasks/bulk/": () => json({ done: 2, failed: 0, results: [] }),
    });
    await routinesApi.day(1, { day: "2026-10-20", branch: ["2", "3"] });
    await routinesApi.history(1, { from: "2026-09-22", to: "2026-10-21", position: ["4"] });
    await routinesApi.toConfirm(1);
    await routinesApi.confirm(1, [5, 6]);
    expect(calls.map((c) => c.url)).toEqual([
      "/api/v1/owner/companies/1/routines/day/?day=2026-10-20&branch=2&branch=3",
      "/api/v1/owner/companies/1/routines/history/?from=2026-09-22&to=2026-10-21&position=4",
      "/api/v1/owner/companies/1/routines/to-confirm/",
      "/api/v1/owner/companies/1/tasks/bulk/",
    ]);
    expect(calls[3]!.body).toEqual({ ids: [5, 6], action: "confirm" });
  });

  it("Today shows each person's run with its proof, who was skipped and why, and confirms in place", async () => {
    const calls = stub({
      "GET tasks/options/": () => json(options),
      "GET routines/day/": () =>
        json({
          day: "2026-10-21",
          holiday: false,
          idle: 1,
          totals: { ...counts, total: 3, finished: 2, routines: 2 },
          routines: [
            {
              routine: ref(4, "Kassani ochish"),
              due_at: "2026-10-21T04:00:00Z",
              reason: null,
              next_run: null,
              give: null,
              progress: { finished: 2, total: 3, percent: 67 },
              counts,
              runs: [
                run(1, "Gani Rahimov", "late"),
                run(2, "Vali Karimov", "review", { completed_at: "2026-10-21T04:20:00Z", on_time: false, can_confirm: true }),
                run(3, "Ali Valiyev", "done", { completed_at: "2026-10-21T03:50:00Z", on_time: true, proof_thumb: "/media/t.webp", proof_photo: "/media/p.jpg" }),
              ],
              skipped: [{ member: { id: 9, name: "Aziza Usmonova", photo_url: null, position: null }, reason: "time_off" }],
            },
            {
              routine: ref(5, "Muddati yaqin dorilarni tekshirish"),
              due_at: "2026-10-21T04:00:00Z",
              reason: "made_late",
              next_run: "2026-10-22T04:00:00Z",
              give: { people: 2, due_at: "2026-10-21T09:30:00Z" },
              progress: { finished: 0, total: 0, percent: null },
              counts: { ...counts, done: 0, review: 0, late: 0, skipped: 0 },
              runs: [],
              skipped: [],
            },
          ],
        }),
      "POST tasks/bulk/": () => json({ done: 1, failed: 0, results: [{ id: 2, ok: true, error: "" }] }),
    });
    const { wrapper } = await mountPage("/c/1/routines", "TodayPage");
    const text = document.body.textContent ?? "";
    expect(text).toContain("Late · due 09:00");
    expect(text).toContain("Waiting · done 09:20");
    expect(text).toContain("Done 08:50");
    expect(text).toContain("2/3 done");
    expect(text).toContain("Aziza Usmonova");
    expect(text).toContain("On time off");
    expect(text).toContain("It starts tomorrow");
    expect(text).toContain("Give today's task now");
    expect(text).toContain("1 routine gives no task this day");
    expect(document.body.querySelectorAll("[data-run-state]")).toHaveLength(3);
    document.body.querySelector<HTMLButtonElement>("[data-run-state=review] button[aria-label=Confirm]")!.click();
    await flushPromises();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ ids: [2], action: "confirm" });
    expect(toasts.at(-1)?.title).toBe("1 confirmed");
    wrapper.unmount();
  });

  it("To confirm confirms a whole group and brings back what was refused", async () => {
    const calls = stub({
      "GET routines/to-confirm/": () =>
        json({
          count: 2,
          groups: [
            {
              routine: ref(4, "Muzlatgich haroratini yozish"),
              day: "2026-10-20",
              items: [
                run(1, "Ali Valiyev", "review", { completed_at: "2026-10-20T03:55:00Z", on_time: true, can_confirm: true, proof_text: "+4 °C" }),
                run(2, "Vali Karimov", "review", { completed_at: "2026-10-20T04:30:00Z", on_time: false, can_confirm: true }),
              ],
            },
          ],
        }),
      "POST tasks/bulk/": () => json({ done: 1, failed: 1, results: [{ id: 1, ok: true, error: "" }, { id: 2, ok: false, error: "You can't confirm this task." }] }),
    });
    const { wrapper } = await mountPage("/c/1/routines/confirm", "ConfirmPage");
    expect(document.body.textContent).toContain("“+4 °C”");
    [...document.body.querySelectorAll("button")].find((b) => b.textContent?.trim() === "Confirm all (2)")!.click();
    await flushPromises();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ ids: [1, 2], action: "confirm" });
    expect(document.body.querySelector("[data-run='1']")).toBeNull();
    expect(document.body.querySelector("[data-run='2']")).not.toBeNull();
    expect(toasts.map((toast) => toast.title)).toEqual(["1 confirmed", "1 couldn't be confirmed"]);
    wrapper.unmount();
  });

  it("History colours each routine's days and a cell opens that day's runs", async () => {
    const cell = (finished: number, made: number) => ({ made, finished, on_time: finished, late: 0, missed: made - finished, open: 0, percent: Math.round((100 * finished) / made), on_time_percent: Math.round((100 * finished) / made) });
    stub({
      "GET tasks/options/": () => json(options),
      "GET routines/history/": () =>
        json({
          range: { from: "2026-10-20", to: "2026-10-21" },
          days: ["2026-10-20", "2026-10-21"],
          routines: [{ routine: ref(4, "Kassani ochish"), cells: [cell(2, 2), null], totals: cell(2, 2) }],
          series: [{ date: "2026-10-20", ...cell(2, 2) }, { date: "2026-10-21", made: 0, finished: 0, on_time: 0, late: 0, missed: 0, open: 0, percent: null, on_time_percent: null }],
          people: [{ member: { id: 11, name: "Ali Valiyev", photo_url: null, position: "Farmatsevt" }, ...cell(1, 2) }],
          totals: cell(2, 2),
        }),
    });
    const { app, wrapper } = await mountPage("/c/1/routines/history", "HistoryPage");
    const heatmap = document.body.querySelector("[data-testid=heatmap]")!;
    const cells = heatmap.querySelectorAll<HTMLButtonElement>("tbody tr:nth-child(2) button");
    expect(cells).toHaveLength(1);
    expect(cells[0]!.getAttribute("title")).toContain("2 of 2 done (100");
    cells[0]!.click();
    await flushPromises();
    expect(app.router.currentRoute.value.name).toBe("routines.today");
    expect(app.router.currentRoute.value.query).toEqual({ day: "2026-10-20", routine: "4" });
    expect(document.body.textContent).toContain("Ali Valiyev");
    wrapper.unmount();
  });
});

describe("Today opened from History", () => {
  it("shows one routine of that day and counts only it", async () => {
    const counts = { done: 1, review: 1, late: 0, missed: 1, returned: 0, open: 0, cancelled: 0, skipped: 0 };
    const row = (id: number, title: string, finished: number, total: number) => ({
      routine: { id, title, due_time: "09:00", branch: null, proof: "none", needs_confirmation: false, is_active: true },
      due_at: "2026-10-20T04:00:00Z",
      reason: null,
      next_run: null,
      give: null,
      progress: { finished, total, percent: Math.round((100 * finished) / total) },
      counts,
      runs: [],
      skipped: [],
    });
    const calls = stub({
      "GET tasks/options/": () => json(options),
      "GET routines/day/": () =>
        json({
          day: "2026-10-20",
          holiday: false,
          idle: 0,
          totals: { ...counts, done: 5, total: 10, finished: 6, routines: 2 },
          routines: [row(4, "Kassani ochish", 2, 3), row(5, "Muzlatgich haroratini yozish", 4, 7)],
        }),
    });
    const app = await testApp("/c/1/routines?day=2026-10-20&routine=4");
    for (const name of ["routines.today", "routines.history", "routines.confirm", "routines.list", "routines.onboarding", "routines.detail"]) {
      app.router.addRoute({ path: `/named/${name}/:id?`, name, component: { render: () => null } });
    }
    const { default: TodayPage } = await import("../pages/TodayPage.vue");
    const { wrapper } = mountWithProviders(TodayPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    expect(calls.find((c) => c.url.includes("routines/day/"))?.url).toContain("day=2026-10-20");
    const text = document.body.textContent ?? "";
    expect(text).toContain("Only “Kassani ochish”");
    expect(text).not.toContain("Muzlatgich haroratini yozish");
    expect(text).toContain("2 / 3");
    expect(text).not.toContain("6 / 10");
    wrapper.unmount();
  });
});

describe("RoutineDetailPage", () => {
  it("says a deleted routine is gone and offers the list instead of trying again", async () => {
    stub({ "GET tasks/options/": () => json(options) });
    const app = await testApp("/c/1/routines/999");
    for (const name of ["routines.today", "routines.history", "routines.confirm", "routines.list", "routines.onboarding"]) {
      app.router.addRoute({ path: `/named/${name}/:id?`, name, component: { render: () => null } });
    }
    app.router.addRoute({ path: "/c/:companyId/routines/:id(\\d+)", name: "routines.detail", component: { render: () => null } });
    await app.router.push("/c/1/routines/999");
    const { default: RoutineDetailPage } = await import("../pages/RoutineDetailPage.vue");
    const { wrapper } = mountWithProviders(RoutineDetailPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    const text = document.body.textContent ?? "";
    expect(text).toContain("This routine no longer exists");
    expect(text).not.toContain("Try again");
    wrapper.unmount();
  });
});
