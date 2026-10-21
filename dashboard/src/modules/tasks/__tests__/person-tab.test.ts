// Person 360 › Tasks and routines: one-off tasks and routine work apart, and a change badge only
// when there is something to compare with.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import PersonTasksTab from "../components/PersonTasksTab.vue";
import en from "../i18n/en.json";
import type { SeriesPoint, TaskSummary } from "../types";

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

const page = (titles: string[] = []) => ({
  count: titles.length,
  next: null,
  previous: null,
  results: titles.map((title, index) => ({
    id: index + 1,
    title,
    status: "todo",
    kind: "assigned",
    priority: "normal",
    due_at: "2026-10-21T15:00:00+05:00",
    is_overdue: false,
    assignee: { id: 7, name: "Alisher Valiyev", photo_url: null },
    project: null,
    routine: null,
    checklist: { done: 0, total: 0 },
    proof: "none",
    proof_thumb: null,
    reward: null,
  })),
});

/** Mounts the tab with `summaries` keyed by the `routines` filter ("without", "only"). */
async function mountTab(summaries: Record<string, TaskSummary>, lists: Record<string, string[]> = {}) {
  const urls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string) => {
      urls.push(input);
      const routines = new URL(input, "http://x").searchParams.get("routines") ?? "";
      if (input.includes("tasks/summary/")) return json(summaries[routines] ?? summary({}));
      return json(page(lists[routines] ?? []));
    }),
  );
  const app = await testApp("/c/1/people/7/tasks");
  const { wrapper } = mountWithProviders(PersonTasksTab, { plugins: app.plugins, props: { memberId: 7 } });
  await flushPromises();
  await flushPromises();
  return { wrapper, urls };
}

/** The change badges on the tab (DeltaBadge labels itself "Up …", "Down …" or "No change"). */
async function changeBadges(data: TaskSummary): Promise<string[]> {
  // One open task, so the block shows its numbers (with nothing at all it is one quiet line).
  const { wrapper } = await mountTab({ without: data }, { without: ["Vitrinani yangilash"] });
  expect(wrapper.text()).toContain(en["tasks.person.done7d"]);
  return wrapper
    .findAll("[aria-label]")
    .map((node) => node.attributes("aria-label")!)
    .filter((label) => /^(Up |Down |No change)/.test(label));
}

const day = (date: string, done: number, total: number, missed = 0): SeriesPoint => ({ date, on_time: done, late: 0, missed, total, done, on_time_percent: total ? (100 * done) / total : null });

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

  it("keeps routine work out of the tasks and shows it in its own block", async () => {
    const { wrapper, urls } = await mountTab({}, { without: ["Vitrinani yangilash"], only: ["Muzlatgich harorati: ertalabki ko‘rsatkich"] });
    const asked = urls.map((url) => new URL(url, "http://x"));
    const tasks = asked.filter((url) => url.searchParams.get("routines") === "without");
    const routines = asked.filter((url) => url.searchParams.get("routines") === "only");
    // One-off: the summary, the open list and what they finished lately.
    expect(tasks.map((url) => url.pathname.replace(/.*companies\/1\//, ""))).toEqual(["tasks/summary/", "tasks/", "tasks/"]);
    // Routine work: its summary and today's runs, done or not.
    expect(routines.map((url) => url.pathname.replace(/.*companies\/1\//, ""))).toEqual(["tasks/summary/", "tasks/"]);
    const runs = routines.find((url) => url.pathname.endsWith("tasks/"))!;
    expect(runs.searchParams.get("due_from")).toBe(runs.searchParams.get("due_to"));
    expect(runs.searchParams.getAll("status")).toContain("done");
    // No list or summary asked for both at once.
    const work = asked.filter((url) => /tasks\/(summary\/)?$/.test(url.pathname));
    expect(work).toHaveLength(5);
    expect(work.every((url) => url.searchParams.has("routines"))).toBe(true);

    const blocks = wrapper.findAll("[data-block]");
    expect(blocks.map((block) => block.attributes("data-block"))).toEqual(["tasks", "routines"]);
    expect(blocks[0]!.text()).toContain("Vitrinani yangilash");
    expect(blocks[0]!.text()).not.toContain("Muzlatgich");
    expect(blocks[1]!.text()).toContain(en["tasks.person.routinesTitle"]);
    expect(blocks[1]!.text()).toContain("Muzlatgich harorati");
  });

  it("says in one line when someone has no one-off tasks, keeping their routine work in view", async () => {
    const { wrapper } = await mountTab({ only: summary({ done_today: 2, total_today: 2 }) }, { only: ["Ombor harorati: ertalab"] });
    const tasks = wrapper.find('[data-block="tasks"]');
    expect(tasks.find("[data-quiet]").text()).toBe(en["tasks.person.noTasks"]);
    expect(tasks.find(".kpi-strip").exists()).toBe(false);
    const routines = wrapper.find('[data-block="routines"]');
    expect(routines.find("[data-quiet]").exists()).toBe(false);
    expect(routines.text()).toContain("Ombor harorati");
  });

  it("counts routine completion and missed runs over the seven days before today", async () => {
    const series = [
      ...Array.from({ length: 6 }, (_, i) => day(`2026-10-0${i + 1}`, 1, 1)),
      day("2026-10-14", 2, 2),
      day("2026-10-15", 2, 2),
      day("2026-10-16", 0, 0),
      day("2026-10-17", 1, 2, 1),
      day("2026-10-18", 2, 2),
      day("2026-10-19", 1, 2, 1),
      day("2026-10-20", 2, 2),
      // Today: one still open and late, which is not "missed" yet.
      day("2026-10-21", 1, 2, 1),
    ];
    const { wrapper } = await mountTab({ only: summary({ done_today: 1, total_today: 2, late_now: 1, series }) });
    const routines = wrapper.find('[data-block="routines"]').text();
    // 14–20 Oct: 10 done of 12 due, 2 missed.
    expect(routines).toContain("83.3%");
    expect(routines).toMatch(/Missed, 7 days\s*2/);
    expect(routines).toContain("1 / 2");
  });
});
