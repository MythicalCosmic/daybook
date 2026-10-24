// What waits for the giver's answer (contracts 5, 7, 8, 10 of the task polish): the drawer's
// "Can't do it" and "Need more time" panels, Seen, @mentions, a stuck reminder run; the reviews
// page's answers and compact cards; the Tasks page's chips; and the helpers behind them.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";

import { confirmQueue } from "@/components/useConfirm";
import { toasts } from "@/components/useToast";
import { mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import TaskDrawer from "../components/TaskDrawer.vue";
import en from "../i18n/en.json";
import { boardOrder, highlightMentions, reminderLag } from "../meta";
import type { TaskDetail, TaskRow } from "../types";

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
      const query = input.split("?")[1] ?? "";
      return (routes[`${call.method} ${path}?${query}`] ?? routes[`${call.method} ${path}`])?.(call) ?? json({ detail: "Not found." }, 404);
    }),
  );
  return calls;
}

const person = (id: number, name: string) => ({ id, name, photo_url: null, position: "Farmatsevt" });

const row = (overrides: Partial<TaskRow> = {}): TaskRow => ({
  id: 7,
  kind: "assigned",
  title: "Update the flu-season shelf",
  status: "todo",
  priority: "normal",
  due_at: "2026-10-26T13:00:00Z",
  for_date: null,
  is_overdue: false,
  assignee: person(12, "Alisher Valiyev"),
  created_by: person(11, "Dilnoza Karimova"),
  branch: { id: 1, name: "Chilonzor", code: "CHL" },
  routine: null,
  project: null,
  proof: "none",
  needs_confirmation: false,
  has_proof: false,
  proof_thumb: null,
  proof_photo: null,
  checklist: { done: 0, total: 0 },
  reward: null,
  started_at: null,
  completed_at: null,
  confirmed_at: null,
  created_at: "2026-10-24T13:30:00Z",
  moves: [],
  seen_at: null,
  blocker: null,
  extension: null,
  ...overrides,
});

const detail = (overrides: Partial<TaskDetail> = {}): TaskDetail => ({
  ...row(),
  description: "",
  proof_text: "",
  confirmed_by: null,
  checklist_items: [],
  comments: [],
  reminders: null,
  actions: ["edit", "cancel", "reassign", "nudge", "comment"],
  last_nudged_at: null,
  ...overrides,
});

const options = { people: [{ ...person(12, "Alisher Valiyev"), branch: "Chilonzor", branch_id: 1, position_id: 3 }, { ...person(14, "Madina Saidova"), branch: "Chilonzor", branch_id: 1, position_id: 4 }, { ...person(15, "Nigora Azimova"), branch: "Yunusobod", branch_id: 2, position_id: 3 }], positions: [], routines: [], policies: [] };

async function openDrawer(task: TaskDetail, routes: Record<string, (call: Call) => Response> = {}) {
  const calls = stub({ "GET tasks/7/": () => json(task), "GET tasks/options/": () => json(options), ...routes });
  const app = await testApp("/c/1/tasks?task=7");
  const { wrapper } = mountWithProviders(TaskDrawer, { plugins: app.plugins });
  await flushPromises();
  await flushPromises();
  return { calls, wrapper };
}
const buttons = () => [...document.body.querySelectorAll("button")];
const button = (label: string) => buttons().find((b) => b.textContent?.trim() === label);

beforeEach(() => {
  mergeModuleMessages("tasks", { en, ru: en, uz: en });
  toasts.splice(0, toasts.length);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
  document.body.innerHTML = "";
});

describe("the drawer: can't do it (contract 7)", () => {
  const blocked = detail({ blocker: { reason_code: "broken", note: "The fridge thermometer is dead", at: "2026-10-25T02:00:00Z" } });

  it("says who can't and why, and drops the duplicate Reassign and Nudge above", async () => {
    const { wrapper } = await openDrawer(blocked);
    const panel = document.body.querySelector("[data-testid=blocker]")!.textContent ?? "";
    expect(panel).toContain("Alisher Valiyev can't do this task");
    // The worker's reason as the app names it, the note in English quotation marks.
    expect(panel).toContain("Equipment broken: “The fridge thermometer is dead”");
    expect(panel).toContain("Reminders are paused");
    expect(buttons().filter((b) => b.textContent?.trim() === "Reassign")).toHaveLength(0);
    expect(button("Nudge now")).toBeUndefined();
    expect(button("Give to someone else")).toBeDefined();
    expect(button("New time")).toBeDefined();
    wrapper.unmount();
  });

  it("cancels through the resolve endpoint after asking", async () => {
    const { calls, wrapper } = await openDrawer(blocked, { "POST tasks/7/blocker/resolve/": () => json(detail({ status: "cancelled", actions: ["comment"] })) });
    [...document.body.querySelectorAll<HTMLButtonElement>("[data-testid=blocker] button")].find((b) => b.textContent?.trim() === "Cancel task")!.click();
    await flushPromises();
    // It asks first (ConfirmHost isn't mounted here: answer the request it queued), and its
    // dismiss button says Close, never a second "Cancel".
    const asked = confirmQueue.value.at(-1)!;
    expect(asked.request.cancelLabel).toBe("Close");
    expect(calls.some((c) => c.url.endsWith("/blocker/resolve/"))).toBe(false);
    asked.resolve({ reason: "" });
    await flushPromises();
    await flushPromises();
    const resolve = calls.find((c) => c.url.endsWith("/tasks/7/blocker/resolve/"));
    expect(resolve?.body).toEqual({ action: "cancel" });
    expect(toasts.at(-1)?.title).toBe("Task cancelled");
    wrapper.unmount();
  });
});

describe("the drawer: need more time (contract 8)", () => {
  it("shows the asked deadline and approves in one tap", async () => {
    const asked = detail({ extension: { until: "2026-10-28T07:00:00Z", note: "The delivery is late", at: "2026-10-25T02:00:00Z" } });
    const { calls, wrapper } = await openDrawer(asked, { "POST tasks/7/extension/decide/": () => json(detail()) });
    const panel = document.body.querySelector("[data-testid=extension]")!.textContent ?? "";
    expect(panel).toContain("Alisher Valiyev asks for more time");
    expect(panel).toContain("“The delivery is late”");
    // Another day: the button names the day as well as the time.
    expect(document.body.querySelector("[data-testid=extension-approve]")!.textContent).toMatch(/Allow · .*28.*12:00/);
    document.body.querySelector<HTMLButtonElement>("[data-testid=extension-approve]")!.click();
    await flushPromises();
    expect(calls.find((c) => c.url.endsWith("/tasks/7/extension/decide/"))?.body).toEqual({ approve: true });
    expect(toasts.at(-1)?.title).toBe("Deadline extended");
    wrapper.unmount();
  });
});

describe("the drawer: seen, reminders, comments", () => {
  it("says when the assignee first opened it, or that they haven't", async () => {
    const first = await openDrawer(detail({ seen_at: "2026-10-25T04:12:00Z" }));
    expect(document.body.querySelector("[data-testid=seen]")!.textContent).toContain("09:12");
    first.wrapper.unmount();
    document.body.innerHTML = "";
    const second = await openDrawer(detail({ seen_at: null }));
    expect(document.body.querySelector("[data-testid=seen]")!.textContent).toContain("Not opened yet");
    second.wrapper.unmount();
    document.body.innerHTML = "";
    // An older backend without the field: no Seen row at all.
    const legacy = detail();
    delete (legacy as Partial<TaskDetail>).seen_at;
    const third = await openDrawer(legacy);
    expect(document.body.querySelector("[data-testid=seen]")).toBeNull();
    third.wrapper.unmount();
  });

  it("never calls finished, started or routine work unopened", async () => {
    // Done from a reminder's button, started from the bot's list, a routine run: no seen_at, yet
    // "Not opened yet" would be false. The row stays away; a time it was seen still shows.
    for (const overrides of [{ status: "done" as const }, { status: "in_progress" as const }, { kind: "daily" as const }]) {
      const { wrapper } = await openDrawer(detail({ seen_at: null, ...overrides }));
      expect(document.body.querySelector("[data-testid=seen]")).toBeNull();
      wrapper.unmount();
      document.body.innerHTML = "";
    }
    const done = await openDrawer(detail({ status: "done", seen_at: "2026-10-25T04:12:00Z" }));
    expect(document.body.querySelector("[data-testid=seen]")!.textContent).toContain("09:12");
    done.wrapper.unmount();
  });

  it("answers C and E inside the open drawer, and not under a dialog above it", async () => {
    const { wrapper } = await openDrawer(detail());
    const press = (key: string) => window.dispatchEvent(new KeyboardEvent("keydown", { key, code: `Key${key.toUpperCase()}`, bubbles: true }));
    // The drawer itself is an open dialog: the keys still work in it.
    expect(document.body.querySelectorAll('[role="dialog"][data-state="open"]').length).toBe(1);
    press("c");
    await flushPromises();
    expect(document.activeElement?.getAttribute("data-testid")).toBe("comment-text");
    (document.activeElement as HTMLElement).blur();
    press("e");
    await flushPromises();
    // The deadline popover opened above the drawer.
    expect(document.body.querySelectorAll('[role="dialog"][data-state="open"]').length).toBe(2);
    // With it open, C waits: the popover is on top.
    press("c");
    await flushPromises();
    expect(document.activeElement?.getAttribute("data-testid")).not.toBe("comment-text");
    wrapper.unmount();
  });

  it("reads a reminder time already passed as going out now, and a long lag as stopped", async () => {
    const plan = (next: string) => ({
      policy: { id: 1, name: "Default" },
      heads_up_minutes: 0,
      every_minutes: 20,
      max_reminders: 12,
      escalate_after: 3,
      sent: 3,
      next_at: next,
      escalated_at: null,
      escalate_to: [],
      snoozed_until: null,
      snoozes_left: 2,
    });
    const soon = await openDrawer(detail({ reminders: plan(new Date(Date.now() - 2 * 60_000).toISOString()) }));
    expect(document.body.querySelector("[data-testid=reminder-next]")!.textContent).toBe("Next reminder: going out now");
    soon.wrapper.unmount();
    document.body.innerHTML = "";
    const stuck = await openDrawer(detail({ reminders: plan(new Date(Date.now() - 47 * 60_000).toISOString()) }));
    const line = document.body.querySelector("[data-testid=reminder-next]")!;
    expect(line.textContent).toBe("Reminders are 47 min behind: they may have stopped");
    expect(line.className).toContain("text-danger");
    stuck.wrapper.unmount();
  });

  it("offers the task's people after @ and sends whom the comment mentions", async () => {
    const { calls, wrapper } = await openDrawer(detail(), {
      "POST tasks/7/comment/": (call) => json({ id: 1, author: person(11, "Dilnoza Karimova"), text: (call.body as { text: string }).text, created_at: "2026-10-25T02:30:00Z" }, 201),
    });
    const area = document.body.querySelector<HTMLTextAreaElement>("[data-testid=comment-text]")!;
    area.value = "Please @ma";
    area.setSelectionRange(area.value.length, area.value.length);
    area.dispatchEvent(new Event("input"));
    await nextTick();
    const list = document.body.querySelector("[data-testid=mention-list]")!;
    // The branch team only (Nigora works in Yunusobod), filtered by what's typed.
    expect([...list.querySelectorAll("[role=option] .truncate.font-medium")].map((o) => o.textContent?.trim())).toEqual(["Madina Saidova"]);
    // The field points at the list and the person a key would pick, for screen readers.
    const option = list.querySelector<HTMLElement>("[role=option]")!;
    expect(area.getAttribute("aria-autocomplete")).toBe("list");
    expect(area.getAttribute("aria-controls")).toBe(list.id);
    expect(area.getAttribute("aria-activedescendant")).toBe(option.id);
    expect(option.getAttribute("aria-selected")).toBe("true");
    expect(option.querySelector("button")).toBeNull(); // nothing to tab to inside an option
    option.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    await nextTick();
    expect(area.value).toBe("Please @Madina Saidova ");
    expect(area.getAttribute("aria-activedescendant")).toBeNull();
    area.value += "check the shelf too";
    area.dispatchEvent(new Event("input"));
    await nextTick();
    document.body.querySelector<HTMLButtonElement>("button[type=submit]")!.click();
    await flushPromises();
    const post = calls.find((c) => c.method === "POST" && c.url.endsWith("/tasks/7/comment/"));
    expect(post?.body).toEqual({ text: "Please @Madina Saidova check the shelf too", mentions: [14] });
    // The sent comment shows the mention marked.
    expect(document.body.querySelector("li .text-accent-fg")?.textContent).toBe("@Madina Saidova");
    wrapper.unmount();
  });

  it("sends no mentions field when nobody is mentioned", async () => {
    const { calls, wrapper } = await openDrawer(detail(), {
      "POST tasks/7/comment/": () => json({ id: 1, author: person(11, "Dilnoza Karimova"), text: "Thanks", created_at: "2026-10-25T02:30:00Z" }, 201),
    });
    const area = document.body.querySelector<HTMLTextAreaElement>("[data-testid=comment-text]")!;
    area.value = "Thanks";
    area.dispatchEvent(new Event("input"));
    await nextTick();
    document.body.querySelector<HTMLButtonElement>("button[type=submit]")!.click();
    await flushPromises();
    expect(calls.find((c) => c.method === "POST" && c.url.endsWith("/tasks/7/comment/"))?.body).toEqual({ text: "Thanks" });
    wrapper.unmount();
  });
});

describe("the reviews page", () => {
  const page = (results: unknown[]) => ({ count: results.length, next: null, previous: null, results });

  it("puts more-time requests and can't-do work first, with Approve right there", async () => {
    const calls = stub({
      "GET tasks/reviews/": () =>
        json(
          page([
            { ...row({ id: 9, status: "review", completed_at: "2026-10-24T10:00:00Z", proof: "text" }), description: "", proof_text: "Done: 12 boxes" },
            { ...row({ id: 10, title: "Count the till", status: "review", due_at: "2026-10-24T08:00:00Z", completed_at: "2026-10-24T10:00:00Z" }), description: "", proof_text: "" },
          ]),
        ),
      "GET tasks/?extension=true&page_size=50": () => json(page([row({ id: 8, title: "Arrange the cabinets", extension: { until: "2026-10-25T13:00:00Z", note: "", at: "2026-10-25T02:00:00Z" } })])),
      "GET tasks/?blocked=true&page_size=50": () => json(page([row({ blocker: { reason_code: "no_stock", note: "", at: "2026-10-25T02:00:00Z" } })])),
      "POST tasks/8/extension/decide/": () => json(detail({ id: 8 })),
    });
    const app = await testApp("/c/1/tasks/reviews");
    const { default: ReviewsPage } = await import("../pages/ReviewsPage.vue");
    const { wrapper } = mountWithProviders(ReviewsPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    const answers = document.body.querySelector("[data-testid=answers]")!;
    expect([...answers.querySelectorAll("[data-answer]")].map((li) => li.getAttribute("data-answer"))).toEqual(["extension", "blocked"]);
    expect(answers.textContent).toContain("Out of stock");
    answers.querySelector<HTMLButtonElement>("[data-testid=answer-approve]")!.click();
    await flushPromises();
    expect(calls.find((c) => c.url.endsWith("/tasks/8/extension/decide/"))?.body).toEqual({ approve: true });
    // Work without a photo: a compact card with what was reported, not an empty picture frame.
    const card = document.body.querySelector("[data-review-card][data-compact]")!;
    expect(card.querySelector("blockquote")?.textContent).toBe("Done: 12 boxes");
    expect(card.querySelector("img")).toBeNull();
    // How late it came in, on the card (R2 T29): only the late one says so.
    expect([...document.body.querySelectorAll("[data-testid=late-by]")].map((el) => el.textContent?.trim())).toEqual(["· late 2 h"]);
    wrapper.unmount();
  });
});

describe("several people checking the same work (audit X-11)", () => {
  const page = (results: unknown[]) => ({ count: results.length, next: null, previous: null, results });
  const waiting = { ...row({ id: 9, status: "review", completed_at: "2026-10-24T10:00:00Z", proof: "text" }), description: "", proof_text: "+4 °C" };

  async function acceptAfterSomeoneElse(stillThere: boolean) {
    let asked = 0;
    stub({
      "GET tasks/reviews/": () => json(page(asked++ === 0 || stillThere ? [waiting] : [])),
      "GET tasks/?extension=true&page_size=50": () => json(page([])),
      "GET tasks/?blocked=true&page_size=50": () => json(page([])),
      "POST tasks/9/confirm/": () => json({ detail: "This task isn't waiting for a check." }, 400),
    });
    const app = await testApp("/c/1/tasks/reviews");
    const { default: ReviewsPage } = await import("../pages/ReviewsPage.vue");
    const { wrapper } = mountWithProviders(ReviewsPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    vi.useFakeTimers({ toFake: ["setTimeout"] });
    [...document.body.querySelectorAll<HTMLButtonElement>("[data-review-card] button")].find((b) => b.textContent?.trim() === "Confirm")!.click();
    await vi.advanceTimersByTimeAsync(5100);
    vi.useRealTimers();
    await flushPromises();
    await flushPromises();
    return wrapper;
  }

  it("lets work someone else decided leave the queue quietly", async () => {
    const wrapper = await acceptAfterSomeoneElse(false);
    expect(document.body.querySelector("[data-review-card]")).toBeNull();
    expect(toasts.at(-1)).toMatchObject({ title: "Someone else already checked it" });
    expect(toasts.some((toast) => toast.title === "This task isn't waiting for a check.")).toBe(false);
    wrapper.unmount();
  });

  it("brings back work still waiting, with the reason it failed", async () => {
    const wrapper = await acceptAfterSomeoneElse(true);
    expect(document.body.querySelector("[data-review-card]")).not.toBeNull();
    expect(toasts.at(-1)).toMatchObject({ title: "This task isn't waiting for a check." });
    wrapper.unmount();
  });
});

describe("the Tasks page's chips", () => {
  const empty = { count: 0, next: null, previous: null, results: [] };
  const summary = { today: "2026-10-25", done_today: 0, total_today: 0, late_now: 0, review: 0, open: 1, on_time_percent: null, on_time_previous: null, done_7d: 0, done_prev_7d: 0, series: [] };

  async function mountTasks(rows: { blocked: TaskRow | null; extension: TaskRow | null }) {
    stub({
      "GET tasks/": () => json(empty),
      "GET tasks/?blocked=true&page_size=1": () => json(rows.blocked ? { count: 2, next: null, previous: null, results: [rows.blocked] } : empty),
      "GET tasks/?extension=true&page_size=1": () => json(rows.extension ? { count: 1, next: null, previous: null, results: [rows.extension] } : empty),
      "GET tasks/summary/": () => json(summary),
      "GET tasks/options/": () => json(options),
      "GET saved-views/": () => json([]),
    });
    const app = await testApp("/c/1/tasks");
    const { default: TasksPage } = await import("../pages/TasksPage.vue");
    const { wrapper } = mountWithProviders(TasksPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    return wrapper;
  }

  it("counts what waits for an answer and opens it", async () => {
    const wrapper = await mountTasks({
      blocked: row({ blocker: { reason_code: "broken", note: "", at: "2026-10-25T02:00:00Z" } }),
      extension: row({ extension: { until: "2026-10-25T13:00:00Z", note: "", at: "2026-10-25T02:00:00Z" } }),
    });
    const chips = [...document.body.querySelectorAll("[data-attention]")];
    expect(chips.map((chip) => chip.textContent?.trim())).toEqual(["Can't do it: 2", "Asking for more time: 1"]);
    expect(chips[1]!.getAttribute("href")).toContain("/tasks/reviews");
    wrapper.unmount();
  });

  it("says how long the oldest check has waited (R2 T32)", async () => {
    stub({
      "GET tasks/": () => json(empty),
      "GET tasks/reviews/": () => json({ count: 1, next: null, previous: null, results: [{ ...row({ status: "review", completed_at: new Date(Date.now() - 3 * 3600_000).toISOString() }), description: "", proof_text: "" }] }),
      "GET tasks/summary/": () => json({ ...summary, review: 1 }),
      "GET tasks/options/": () => json(options),
      "GET saved-views/": () => json([]),
    });
    const app = await testApp("/c/1/tasks");
    const { default: TasksPage } = await import("../pages/TasksPage.vue");
    const { wrapper } = mountWithProviders(TasksPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    expect(wrapper.text()).toContain("One-off tasks · the oldest has waited 3 h");
    wrapper.unmount();
  });

  it("shows no chip when a backend ignores the filter (its row isn't blocked)", async () => {
    const wrapper = await mountTasks({ blocked: row(), extension: null });
    expect(document.body.querySelector("[data-testid=attention]")).toBeNull();
    wrapper.unmount();
  });
});

describe("helpers", () => {
  it("stands late, then urgent cards first in open columns, keeping the server's order otherwise", () => {
    const cards = [
      row({ id: 1 }),
      row({ id: 2, priority: "urgent" }),
      row({ id: 3, is_overdue: true }),
      row({ id: 4, status: "review", priority: "urgent" }),
      row({ id: 5 }),
    ];
    expect(boardOrder(cards).map((card) => card.id)).toEqual([3, 2, 1, 4, 5]);
  });

  it("marks @mentions of known people, longest name first", () => {
    expect(highlightMentions("Hi @Ali Valiyev and @Ali", ["Ali", "Ali Valiyev"])).toEqual([
      { text: "Hi ", mention: false },
      { text: "@Ali Valiyev", mention: true },
      { text: " and ", mention: false },
      { text: "@Ali", mention: true },
    ]);
    expect(highlightMentions("no mention here", ["Ali"])).toEqual([{ text: "no mention here", mention: false }]);
  });

  it("measures how far a reminder is behind", () => {
    const now = new Date("2026-10-25T10:00:00Z");
    expect(reminderLag("2026-10-25T09:53:00Z", now)).toBe(7);
    expect(reminderLag("2026-10-25T10:20:00Z", now)).toBe(-20);
  });
});
