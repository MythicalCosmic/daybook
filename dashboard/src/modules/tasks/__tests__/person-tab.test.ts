// Person 360 › Tasks: a change badge only when there is something to compare with.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import PersonTasksTab from "../components/PersonTasksTab.vue";
import en from "../i18n/en.json";
import type { TaskSummary } from "../types";

const summary = (overrides: Partial<TaskSummary>): TaskSummary => ({
  today: "2026-10-21",
  done_today: 0,
  total_today: 0,
  late_now: 0,
  review: 0,
  open: 0,
  on_time_percent: null,
  on_time_previous: null,
  done_7d: 0,
  done_prev_7d: 0,
  series: [],
  ...overrides,
});

/** The change badges on the tab (DeltaBadge labels itself "Up …", "Down …" or "No change"). */
async function changeBadges(data: TaskSummary): Promise<string[]> {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string) => (input.includes("tasks/summary/") ? json(data) : json({ count: 0, next: null, previous: null, results: [] }))),
  );
  const app = await testApp("/c/1/people/7/tasks");
  const { wrapper } = mountWithProviders(PersonTasksTab, { plugins: app.plugins, props: { memberId: 7 } });
  await flushPromises();
  await flushPromises();
  expect(wrapper.text()).toContain(en["tasks.person.done7d"]);
  return wrapper
    .findAll("[aria-label]")
    .map((node) => node.attributes("aria-label")!)
    .filter((label) => /^(Up |Down |No change)/.test(label));
}

beforeEach(() => {
  mergeModuleMessages("tasks", { en, ru: en, uz: en });
});

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("PersonTasksTab", () => {
  it("shows no empty change badges for someone with nothing to compare", async () => {
    expect(await changeBadges(summary({}))).toEqual([]);
    // Last week had nothing done: a change from zero says nothing either.
    expect(await changeBadges(summary({ on_time_percent: 80, done_7d: 4 }))).toEqual([]);
  });

  it("keeps the badges when last week had numbers", async () => {
    const labels = await changeBadges(summary({ on_time_percent: 76.2, on_time_previous: 90.5, done_7d: 18, done_prev_7d: 21 }));
    expect(labels).toHaveLength(2);
    expect(labels.every((label) => label.startsWith("Down "))).toBe(true);
  });
});
