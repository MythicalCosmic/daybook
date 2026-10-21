// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { toasts } from "@/components/useToast";
import { mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import { filterParams, moveInColumns, taskKeys, tasksApi } from "../api";
import TaskDrawer from "../components/TaskDrawer.vue";
import TaskTimeline from "../components/TaskTimeline.vue";
import { builtinTabs, builtinViews, filterDefs, viewParams } from "../filters";
import en from "../i18n/en.json";
import module from "../index";
import { lateness, minutesBetween, zonedIso, zonedParts } from "../meta";
import type { BoardColumn, TaskDetail, TaskRow } from "../types";

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

const person = (id: number, name: string) => ({ id, name, photo_url: null, position: "Cashier" });

const row = (overrides: Partial<TaskRow> = {}): TaskRow => ({
  id: 7,
  kind: "assigned",
  title: "Count the drinks fridge",
  status: "review",
  priority: "normal",
  due_at: "2026-10-21T13:00:00Z",
  for_date: null,
  is_overdue: false,
  assignee: person(11, "Madina Saidova"),
  created_by: person(1, "Dilnoza Karimova"),
  branch: { id: 1, name: "Chilonzor", code: "CHL" },
  routine: null,
  project: null,
  proof: "photo",
  needs_confirmation: true,
  has_proof: true,
  proof_thumb: "/media/proofs/thumbs/1/a.webp",
  proof_photo: "/media/proofs/1/a.jpg",
  checklist: { done: 2, total: 3 },
  reward: "50000.00",
  started_at: null,
  completed_at: "2026-10-21T12:40:00Z",
  confirmed_at: null,
  created_at: "2026-10-21T08:00:00Z",
  moves: ["done", "returned"],
  ...overrides,
});

const detail = (overrides: Partial<TaskDetail> = {}): TaskDetail => ({
  ...row(),
  description: "Every shelf, front to back.",
  proof_text: "",
  confirmed_by: null,
  checklist_items: [
    { id: 1, text: "Top shelf", is_done: true },
    { id: 2, text: "Middle shelf", is_done: true },
    { id: 3, text: "Bottom shelf", is_done: false },
  ],
  comments: [],
  reminders: null,
  actions: ["confirm", "return", "edit", "cancel", "reassign", "comment"],
  last_nudged_at: null,
  ...overrides,
});

beforeEach(() => {
  mergeModuleMessages("tasks", { en, ru: en, uz: en });
  toasts.splice(0, toasts.length);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

describe("api", () => {
  it("calls the owner task endpoints with the right methods and bodies", async () => {
    const calls = stub({
      "GET tasks/": () => json({ count: 0, next: null, previous: null, results: [] }),
      "POST tasks/7/confirm/": () => json(detail({ status: "done" })),
      "POST tasks/7/return/": () => json(detail({ status: "returned" })),
      "POST tasks/7/reassign/": () => json(detail()),
      "POST tasks/7/nudge/": () => json({ nudged_at: "2026-10-21T13:10:00Z" }),
      "POST tasks/7/move/": () => json(detail({ status: "in_progress" })),
      "POST tasks/bulk/": () => json({ results: [] }),
      "POST tasks/": () => json({ created: 2, ids: [8, 9] }, 201),
    });
    await tasksApi.list(1, { status: ["todo", "review"], overdue: "true", page: 2 });
    await tasksApi.confirm(1, 7);
    await tasksApi.sendBack(1, 7, "The photo is blurry");
    await tasksApi.reassign(1, 7, 12);
    await tasksApi.nudge(1, 7);
    await tasksApi.move(1, 7, "in_progress");
    await tasksApi.bulk(1, { ids: [7, 8], action: "reschedule", payload: { shift_days: 1 } });
    await tasksApi.create(1, { title: "Wipe the windows", assignee_ids: [11, 12], due_at: "2026-10-22T04:00:00Z" } as never);
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
      "GET /api/v1/owner/companies/1/tasks/?status=todo&status=review&overdue=true&page=2",
      "POST /api/v1/owner/companies/1/tasks/7/confirm/",
      "POST /api/v1/owner/companies/1/tasks/7/return/",
      "POST /api/v1/owner/companies/1/tasks/7/reassign/",
      "POST /api/v1/owner/companies/1/tasks/7/nudge/",
      "POST /api/v1/owner/companies/1/tasks/7/move/",
      "POST /api/v1/owner/companies/1/tasks/bulk/",
      "POST /api/v1/owner/companies/1/tasks/",
    ]);
    expect(calls[2]!.body).toEqual({ reason: "The photo is blurry" });
    expect(calls[3]!.body).toEqual({ assignee_id: 12 });
    expect(calls[5]!.body).toEqual({ to: "in_progress", reason: "" });
    expect(calls[6]!.body).toEqual({ ids: [7, 8], action: "reschedule", payload: { shift_days: 1 } });
  });

  it("drops empty filters and keys queries per company", () => {
    expect(filterParams({ status: ["todo"], assignee: [], q: "", overdue: undefined, branch: ["1"] } as never)).toEqual({ status: ["todo"], branch: ["1"] });
    expect(taskKeys.detail(1, 7)).toEqual([1, "tasks", "detail", { id: 7 }]);
    expect(taskKeys.all(1)).toEqual([1, "tasks"]);
  });

  it("moves a card to the top of its new column and fixes the counts", () => {
    const task = row({ status: "review" });
    const other = row({ id: 8, status: "done" });
    const columns: BoardColumn[] = [
      { id: "review", count: 1, items: [task] },
      { id: "done", count: 1, items: [other] },
    ];
    const moved = moveInColumns(columns, task, "done");
    expect(moved[0]).toMatchObject({ id: "review", count: 0, items: [] });
    expect(moved[1]!.count).toBe(2);
    expect(moved[1]!.items.map((item) => [item.id, item.status])).toEqual([
      [7, "done"],
      [8, "done"],
    ]);
  });

  it("registers in Work with the review badge and the plan's permissions", () => {
    expect(module).toMatchObject({ id: "tasks", group: "work", order: 10 });
    expect(module.perm).toEqual(["tasks.view_all", "tasks.confirm", "tasks.assign"]);
    expect(module.widgets?.map((w) => w.id)).toEqual(["tasks.kpi.done_today", "tasks.kpi.on_time", "tasks.kpi.late_now", "tasks.chart.on_time_trend", "tasks.top_bottom"]);
  });
});

describe("filters and views", () => {
  const t = (key: string) => (en as Record<string, string>)[key] ?? key;

  it("keeps filters, the URL and saved views the same object", () => {
    const views = builtinViews("2026-10-21");
    expect(views.find((v) => v.id === "today")?.params).toEqual({ due_from: "2026-10-21", due_to: "2026-10-21" });
    expect(views.find((v) => v.id === "open")?.params.status).toEqual(["todo", "in_progress", "review", "returned"]);
    // Saved state may carry the view and ordering; only filters come back, as strings.
    expect(viewParams({ params: { status: ["todo"], overdue: true, view: "board", ordering: "-due_at", q: "" } })).toEqual({ status: ["todo"], overdue: "true" });
    expect(viewParams({ assignee: [11, 12] })).toEqual({ assignee: ["11", "12"] });
  });

  it("shows personal tasks only to owners", () => {
    const views = builtinViews("2026-10-21");
    expect(builtinTabs(t, views, true).map((tab) => tab.id)).toContain("personal");
    expect(builtinTabs(t, views, false).map((tab) => tab.id)).not.toContain("personal");
    const kinds = (owner: boolean) => (filterDefs(t, undefined, [], owner).find((def) => def.key === "kind") as { options: Array<{ value: string }> }).options.map((o) => o.value);
    expect(kinds(true)).toEqual(["daily", "assigned", "personal"]);
    expect(kinds(false)).toEqual(["daily", "assigned"]);
  });
});

describe("meta", () => {
  it("says how late, and converts company-local times both ways", () => {
    const words = { min: "min", h: "h", d: "d" };
    expect(lateness(45, words)).toBe("45 min");
    expect(lateness(130, words)).toBe("2 h");
    expect(lateness(100, words)).toBe("2 h");
    expect(lateness(120, words)).toBe("2 h");
    expect(lateness(19 * 60 + 36, words)).toBe("20 h");
    expect(lateness(60 * 50, words)).toBe("2 d");
    expect(lateness(23 * 60 + 50, words)).toBe("1 d");
    expect(minutesBetween("2026-10-21T10:00:00Z", "2026-10-21T11:30:00Z")).toBe(90);
    const iso = zonedIso("2026-10-21", "18:00", "Asia/Tashkent");
    expect(new Date(iso).toISOString()).toBe("2026-10-21T13:00:00.000Z");
    expect(zonedParts(iso, "Asia/Tashkent")).toEqual({ day: "2026-10-21", time: "18:00" });
  });
});

describe("TaskDrawer", () => {
  it("opens from ?task=, shows the proof and checklist, and accepts the work", async () => {
    const calls = stub({
      "GET tasks/7/": () => json(detail()),
      "GET tasks/options/": () => json({ people: [], positions: [], routines: [], policies: [] }),
      "POST tasks/7/confirm/": () => json(detail({ status: "done", actions: ["comment"], confirmed_at: "2026-10-21T13:05:00Z" })),
    });
    const app = await testApp("/c/1/tasks?task=7");
    const { wrapper } = mountWithProviders(TaskDrawer, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    const text = document.body.textContent ?? "";
    expect(text).toContain("Count the drinks fridge");
    expect(text).toContain("Madina Saidova");
    expect(text).toContain("Middle shelf");
    expect(document.body.querySelector('img[src="/media/proofs/thumbs/1/a.webp"], img[src="/media/proofs/1/a.jpg"]')).not.toBeNull();
    const accept = [...document.body.querySelectorAll("button")].find((b) => b.textContent?.trim() === "Accept");
    expect(accept).toBeDefined();
    accept!.click();
    await flushPromises();
    expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/tasks/7/confirm/"))).toBe(true);
    expect(toasts.at(-1)?.title).toBe("Accepted");
    wrapper.unmount();
  });

  it("gives the drawer's extensions the task and its routine (knowledge's How to do this)", async () => {
    const link = (target_type: string, target_id: number, title: string) => ({
      id: target_id,
      target_type,
      target_id,
      target_title: "",
      page: { id: 40 + target_id, title, emoji: "📄", space: { id: 1, name: "Shop", emoji: "🏪" } },
      created_at: "2026-10-01T09:00:00Z",
    });
    const calls = stub({
      "GET tasks/7/": () => json(detail({ routine: { id: 3, title: "Close the till", onboarding: false } })),
      "GET tasks/options/": () => json({ people: [], positions: [], routines: [], policies: [] }),
      "GET knowledge/pages/linked/": (call) =>
        json(call.url.includes("target_type=routine") ? [link("routine", 3, "Closing the till")] : [link("task", 7, "Counting fridges")]),
    });
    const app = await testApp("/c/1/tasks?task=7");
    const { wrapper } = mountWithProviders(TaskDrawer, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    await flushPromises();
    const asked = calls.filter((c) => c.url.includes("knowledge/pages/linked/")).map((c) => new URL(c.url, "http://x").searchParams.toString());
    expect(asked.sort()).toEqual(["target_type=routine&target_id=3", "target_type=task&target_id=7"]);
    const text = document.body.textContent ?? "";
    expect(text).toContain("Closing the till");
    expect(text).toContain("Counting fridges");
    expect(document.body.querySelector('a[href="/dashboard/c/1/knowledge/p/43"], a[href="/c/1/knowledge/p/43"]')).not.toBeNull();
    wrapper.unmount();
  });

  it("hides the actions the caller may not take", async () => {
    stub({
      "GET tasks/7/": () => json(detail({ status: "todo", actions: ["comment"] })),
      "GET tasks/options/": () => json({ people: [], positions: [], routines: [], policies: [] }),
    });
    const app = await testApp("/c/1/tasks?task=7");
    const { wrapper } = mountWithProviders(TaskDrawer, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    const labels = [...document.body.querySelectorAll("button")].map((b) => b.textContent?.trim());
    expect(labels).not.toContain("Accept");
    expect(labels).not.toContain("Send back");
    wrapper.unmount();
  });
});

describe("TaskTimeline", () => {
  it("names each person once, in the sentence of their language", async () => {
    stub({
      "GET tasks/7/timeline/": () =>
        json([
          { at: "2026-10-21T08:00:00Z", kind: "created", action: "created", actor: person(1, "Dilnoza Karimova"), text: "", meta: {} },
          { at: "2026-10-21T09:00:00Z", kind: "comment", action: "comment", actor: person(2, "Bekzod Mirzayev"), text: "Phone: Sharq Savdo", meta: {} },
          { at: "2026-10-21T10:00:00Z", kind: "reminder", action: "reminder", actor: person(11, "Madina Saidova"), text: "", meta: { step: 2, delivered: true } },
        ]),
    });
    const app = await testApp("/c/1/tasks?task=7");
    const { wrapper } = mountWithProviders(TaskTimeline, { props: { taskId: 7 }, plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    const text = wrapper.text();
    expect(text).toContain("Bekzod Mirzayev commented");
    expect(text.match(/Bekzod Mirzayev/g)).toHaveLength(1);
    expect(text).toContain("Phone: Sharq Savdo");
    expect(text).toContain("Reminder 2 sent to Madina Saidova");
    wrapper.unmount();
  });
});

describe("reviews", () => {
  it("reads the queue as review cards (no comments or reminder plan per card)", async () => {
    const calls = stub({
      "GET tasks/reviews/": () => json({ count: 1, next: null, previous: null, results: [{ ...row(), description: "", proof_text: "+4 °C" }] }),
    });
    const page = await tasksApi.reviews(1, { page_size: 100 });
    expect(page.results[0]!.proof_text).toBe("+4 °C");
    expect(calls[0]!.url).toContain("/tasks/reviews/?page_size=100");
  });
});
