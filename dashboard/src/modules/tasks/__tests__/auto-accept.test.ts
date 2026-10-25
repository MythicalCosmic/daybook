// Finished tasks accepted automatically (PLAN-OWNER §15.3): the Settings → Tasks panel, the new
// task dialog starting from the company's rule, and "Accepted" wherever a task's status shows.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";

import PersonPicker from "@/components/PersonPicker.vue";
import { toasts } from "@/components/useToast";
import { findModule } from "@/core/modules";
import { mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import CreateTaskDialog from "../components/CreateTaskDialog.vue";
import TasksSettingsPanel from "../components/TasksSettingsPanel.vue";
import TaskStatusPill from "../components/TaskStatusPill.vue";
import TaskTimeline from "../components/TaskTimeline.vue";
import en from "../i18n/en.json";
import ru from "../i18n/ru.json";
import uz from "../i18n/uz.json";
import { forgetQuickAddAvailability } from "../quickAdd";

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

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const text = () => document.body.textContent ?? "";

beforeEach(() => {
  mergeModuleMessages("tasks", { en, ru, uz });
  toasts.splice(0, toasts.length);
  forgetQuickAddAvailability();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

describe("Settings → Tasks", () => {
  it("is a settings panel for people who change the company's settings", () => {
    const panel = findModule("tasks")?.settings?.find((item) => item.id === "tasks");
    expect(panel).toMatchObject({ title: "tasks.settings.title", perm: "company.settings" });
  });

  async function open(settings: { on_finish: string; auto_accept_after_hours: number | null }) {
    const calls = stub({
      "GET tasks/settings/": () => json(settings),
      "PATCH tasks/settings/": (call) => json({ ...settings, ...(call.body as object) }),
    });
    const app = await testApp("/c/1/settings/tasks");
    const { wrapper } = mountWithProviders(TasksSettingsPanel, { plugins: app.plugins });
    await flushPromises();
    return { calls, wrapper };
  }

  it("offers the three rules with the company's checked, and saves a new one at once", async () => {
    const { calls, wrapper } = await open({ on_finish: "auto", auto_accept_after_hours: null });
    const radios = [...document.body.querySelectorAll("[role=radio]")];
    expect(radios).toHaveLength(3);
    expect(text()).toContain("When someone finishes a task");
    expect(text()).toContain("Accept it automatically");
    expect(text()).toContain("Accept automatically only with a photo or text proof, otherwise ask");
    expect(text()).toContain("Always ask the person who gave it");
    expect(radios[0]!.getAttribute("aria-checked")).toBe("true");
    (radios[2] as HTMLElement).click();
    await flushPromises();
    const saves = calls.filter((call) => call.method === "PATCH");
    expect(saves.map((call) => call.body)).toEqual([{ on_finish: "ask" }]);
    expect(toasts.at(-1)?.title).toBe("Saved");
    wrapper.unmount();
  });

  it("shows the wait for a review: never, or after so many hours", async () => {
    const { wrapper } = await open({ on_finish: "ask", auto_accept_after_hours: null });
    expect(text()).toContain("If nobody reviews it in time");
    expect(text()).toContain("Never accept it automatically");
    wrapper.unmount();
    document.body.innerHTML = "";
    const again = await open({ on_finish: "ask", auto_accept_after_hours: 24 });
    expect(text()).toContain("Accept it automatically after 24 hours");
    again.wrapper.unmount();
  });

  it("reads in Uzbek and Russian without emoji", () => {
    const keys = Object.keys(en).filter((key) => key.startsWith("tasks.settings.") || key.startsWith("tasks.accepted.") || key === "tasks.status.accepted");
    expect(keys.length).toBeGreaterThan(10);
    const emoji = /[\p{Extended_Pictographic}\u{FE0F}]/u;
    for (const dictionary of [en, uz, ru] as Array<Record<string, string>>) {
      for (const key of keys) {
        expect(dictionary[key], key).toBeTruthy();
        expect(emoji.test(dictionary[key]!), key).toBe(false);
      }
    }
    expect((uz as Record<string, string>)["tasks.status.accepted"]).toBe("Qabul qilindi");
    expect((ru as Record<string, string>)["tasks.status.accepted"]).toBe("Принято");
  });
});

describe("New task starts from the company's rule", () => {
  const person = { id: 12, name: "Alisher Valiyev", photo_url: null, position: "Farmatsevt", branch: "Chilonzor", branch_id: 1, position_id: 3 };

  async function open(onFinish: string) {
    const calls = stub({
      "GET tasks/options/": () => json({ people: [person], positions: [], routines: [], policies: [] }),
      "GET tasks/settings/": () => json({ on_finish: onFinish, auto_accept_after_hours: null }),
      "POST tasks/": () => json({ created: 1, ids: [41] }, 201),
    });
    const app = await testApp("/c/1/tasks");
    const { wrapper } = mountWithProviders(CreateTaskDialog, { plugins: app.plugins, props: { open: true } });
    await flushPromises();
    wrapper.findComponent(PersonPicker).vm.$emit("update:modelValue", [12]);
    const input = document.body.querySelector<HTMLInputElement>("input[data-testid=create-title]")!;
    input.value = "Vitrinani artish";
    input.dispatchEvent(new Event("input"));
    await nextTick();
    return { calls, wrapper };
  }

  const toggle = () => document.body.querySelector<HTMLButtonElement>("[role=switch]")!;
  async function create(calls: Call[]) {
    [...document.body.querySelectorAll("button")].find((b) => b.textContent?.includes("Create"))!.click();
    await wait(400);
    await flushPromises();
    return calls.filter((c) => c.method === "POST" && c.url.endsWith("/companies/1/tasks/"));
  }

  it("says the rule and leaves the choice to it when untouched", async () => {
    const { calls, wrapper } = await open("ask");
    expect(toggle().getAttribute("aria-checked")).toBe("true");
    expect(text()).toContain("Company rule: you check every finished task");
    const [save] = await create(calls);
    expect(save!.body).toMatchObject({ needs_confirmation: null, assignee_ids: [12] });
    wrapper.unmount();
  });

  it("sends the giver's own choice once the switch is touched", async () => {
    const { calls, wrapper } = await open("auto");
    expect(toggle().getAttribute("aria-checked")).toBe("false");
    expect(text()).toContain("Company rule: accepted automatically when it's finished");
    toggle().click();
    await nextTick();
    expect(text()).toContain("It waits for your check before it counts as done");
    const [save] = await create(calls);
    expect(save!.body).toMatchObject({ needs_confirmation: true });
    wrapper.unmount();
  });
});

describe("Accepted, wherever the status shows", () => {
  it("reads Accepted for finished work nobody had to check", async () => {
    const app = await testApp("/c/1/tasks");
    const { wrapper } = mountWithProviders(TaskStatusPill, { plugins: app.plugins, props: { status: "done", accepted: true } });
    expect(wrapper.text()).toBe("Accepted");
    wrapper.unmount();
    const done = mountWithProviders(TaskStatusPill, { plugins: app.plugins, props: { status: "done" } });
    expect(done.wrapper.text()).toBe("Done");
    done.wrapper.unmount();
  });

  it("says in the history when it was accepted automatically", async () => {
    const worker = { id: 12, name: "Alisher Valiyev", photo_url: null };
    stub({
      "GET tasks/7/timeline/": () =>
        json([
          { at: "2026-10-25T08:00:00Z", kind: "completed", action: "completed", actor: worker, text: "", meta: { accepted: "auto" } },
          { at: "2026-10-25T09:00:00Z", kind: "completed", action: "completed", actor: worker, text: "", meta: {} },
          { at: "2026-10-25T17:00:00Z", kind: "audit", action: "tasks.auto_accepted", actor: null, text: "Accepted automatically", meta: { hours: 8 } },
        ]),
    });
    const app = await testApp("/c/1/tasks");
    const { wrapper } = mountWithProviders(TaskTimeline, { plugins: app.plugins, props: { taskId: 7 } });
    await flushPromises();
    expect(text()).toContain("Alisher Valiyev finished it, accepted automatically");
    expect(text()).toContain("Accepted automatically: nobody checked it within 8 hours");
    wrapper.unmount();
  });
});

describe("the empty reviews page says the company's rule", () => {
  it("explains why little comes here, with a way to change it for owners", async () => {
    const empty = { count: 0, next: null, previous: null, results: [] };
    stub({
      "GET tasks/reviews/": () => json(empty),
      "GET tasks/": () => json(empty),
      "GET tasks/settings/": () => json({ on_finish: "auto", auto_accept_after_hours: null }),
    });
    const app = await testApp("/c/1/tasks/reviews");
    const { default: ReviewsPage } = await import("../pages/ReviewsPage.vue");
    const { wrapper } = mountWithProviders(ReviewsPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    const note = document.body.querySelector("[data-testid=reviews-rule]");
    expect(note?.textContent).toContain("Company rule: finished work is accepted automatically; only tasks that ask for a check come here.");
    expect(note?.querySelector("a")?.getAttribute("href")).toContain("/settings/tasks");
    wrapper.unmount();
  });

  it("says the rule and the wait above the work waiting for a check too", async () => {
    const empty = { count: 0, next: null, previous: null, results: [] };
    const person = (id: number, name: string) => ({ id, name, photo_url: null, position: "Farmatsevt" });
    const waiting = {
      id: 7,
      kind: "assigned",
      title: "Count the stockroom",
      status: "review",
      priority: "normal",
      due_at: null,
      for_date: null,
      is_overdue: false,
      assignee: person(12, "Alisher Valiyev"),
      created_by: person(11, "Bekzod Mirzayev"),
      branch: { id: 1, name: "Chilonzor", code: "CHL" },
      routine: null,
      project: null,
      proof: "none",
      needs_confirmation: true,
      has_proof: false,
      proof_thumb: null,
      proof_photo: null,
      checklist: { done: 0, total: 0 },
      reward: null,
      started_at: null,
      completed_at: "2026-10-25T21:22:00Z",
      confirmed_at: null,
      created_at: "2026-10-25T20:00:00Z",
      moves: [],
      seen_at: null,
      blocker: null,
      extension: null,
    };
    stub({
      "GET tasks/reviews/": () => json({ count: 1, next: null, previous: null, results: [waiting] }),
      "GET tasks/": () => json(empty),
      "GET tasks/settings/": () => json({ on_finish: "auto", auto_accept_after_hours: 8 }),
    });
    const app = await testApp("/c/1/tasks/reviews");
    const { default: ReviewsPage } = await import("../pages/ReviewsPage.vue");
    const { wrapper } = mountWithProviders(ReviewsPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    expect(text()).toContain("Count the stockroom");
    const note = document.body.querySelector("[data-testid=reviews-rule-top]");
    expect(note?.textContent).toContain("Company rule: finished work is accepted automatically; only tasks that ask for a check come here.");
    expect(note?.textContent).toContain("If nobody checks it within 8 h, it is accepted automatically.");
    expect(document.body.querySelector("[data-testid=reviews-rule]")).toBeNull();
    wrapper.unmount();
  });
});
