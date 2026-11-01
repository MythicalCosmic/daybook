// Round 2: the Tasks page's KPI strip says when it failed, and the "oldest waits" hint asks for one row.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { toasts } from "@/components/useToast";
import { mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import en from "../i18n/en.json";
import TasksPage from "../pages/TasksPage.vue";

interface Call {
  method: string;
  url: string;
}

const empty = { count: 0, next: null, previous: null, results: [] };
const summary = { today: "2026-10-25", done_today: 0, total_today: 0, late_now: 0, review: 0, open: 1, on_time_percent: null, on_time_previous: null, done_7d: 0, done_prev_7d: 0, series: [] };
const options = { people: [], branches: [], templates: [], can_assign_others: true, routines: [] };

function stub(failSummary: boolean): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const call = { method: init?.method ?? "GET", url: input };
      calls.push(call);
      const path = input.replace("/api/v1/owner/companies/1/", "").split("?")[0]!;
      if (path === "tasks/summary/") return failSummary ? json({ detail: "Server error." }, 500) : json(summary);
      if (path === "tasks/options/") return json(options);
      if (path === "saved-views/") return json([]);
      return json(empty);
    }),
  );
  return calls;
}

async function mountTasks(failSummary = false) {
  const calls = stub(failSummary);
  const app = await testApp("/c/1/tasks");
  const { wrapper } = mountWithProviders(TasksPage, { plugins: app.plugins });
  await flushPromises();
  await flushPromises();
  return { wrapper, calls };
}

beforeEach(() => {
  mergeModuleMessages("tasks", { en, ru: en, uz: en });
  toasts.splice(0, toasts.length);
});

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("TasksPage", () => {
  it("shows Try again when the KPI summary fails", async () => {
    const { wrapper, calls } = await mountTasks(true);
    const retry = [...document.body.querySelectorAll("button")].find((b) => b.textContent?.trim() === "Try again");
    expect(retry).toBeTruthy();
    const before = calls.filter((c) => c.url.includes("/tasks/summary/")).length;
    retry!.click();
    await flushPromises();
    expect(calls.filter((c) => c.url.includes("/tasks/summary/")).length).toBe(before + 1);
    wrapper.unmount();
  });

  it("asks the review queue for one row for its hint, not a hundred", async () => {
    const { wrapper, calls } = await mountTasks();
    const reviews = calls.filter((c) => c.url.includes("/tasks/reviews/"));
    expect(reviews.length).toBeGreaterThan(0);
    for (const call of reviews) expect(new URL(call.url, "http://x").searchParams.get("page_size")).toBe("1");
    wrapper.unmount();
  });
});
