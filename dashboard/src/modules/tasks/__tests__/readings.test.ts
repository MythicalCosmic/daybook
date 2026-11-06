// Storage readings in the tasks module (PLAN-OWNER §14.10): the drawer's Readings section (each
// spec with its allowed range, the values typed in with their state, who, when, the note and any
// recheck) and the Overview card of today's excursions and missed readings, which a company that
// never set readings up never sees.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mergeModuleMessages } from "@/i18n";
import { formatNumber } from "@/lib/format";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import TaskDrawer from "../components/TaskDrawer.vue";
import en from "../i18n/en.json";
import ru from "../i18n/ru.json";
import uz from "../i18n/uz.json";
import module from "../index";
import { rangeText, readingGroups, valueText } from "../readings";
import type { ReadingSpec, ReadingTaken, ReadingsToday, TaskDetail } from "../types";
import ReadingsTodayWidget from "../widgets/ReadingsTodayWidget.vue";

const person = (id: number, name: string) => ({ id, name, photo_url: null, position: "Farmatsevt" });

const FRIDGE: ReadingSpec = { key: "t", label: "Fridge 2 temperature", unit: "°C", min: "2.0", max: "8.0", critical: true };
const HUMIDITY: ReadingSpec = { key: "h", label: "Humidity", unit: "%", min: null, max: "60.0", critical: false };

const taken = (overrides: Partial<ReadingTaken> = {}): ReadingTaken => ({
  id: 1,
  key: "t",
  label: "Fridge 2 temperature",
  unit: "°C",
  value: "8.90",
  min: "2.00",
  max: "8.00",
  in_range: false,
  note: "The door was left open: vaccines moved to fridge 1",
  is_recheck: false,
  recorded_at: "2026-10-23T15:05:00Z",
  recorded_by: { id: 12, name: "Alisher Valiyev" },
  ...overrides,
});

const detail = (overrides: Partial<TaskDetail> = {}): TaskDetail => ({
  id: 7,
  kind: "daily",
  title: "Fridge 2: temperature, 20:00",
  status: "done",
  priority: "normal",
  due_at: "2026-10-23T15:00:00Z",
  for_date: "2026-10-23",
  is_overdue: false,
  assignee: person(12, "Alisher Valiyev"),
  created_by: null,
  branch: { id: 1, name: "Yunusobod", code: "YNS" },
  routine: { id: 40, title: "Fridge 2: temperature, 20:00", onboarding: false },
  project: null,
  proof: "readings",
  needs_confirmation: false,
  has_proof: false,
  proof_thumb: null,
  proof_photo: null,
  checklist: { done: 0, total: 0 },
  reward: null,
  started_at: null,
  completed_at: "2026-10-23T15:05:00Z",
  confirmed_at: null,
  created_at: "2026-10-23T03:00:00Z",
  moves: [],
  seen_at: null,
  blocker: null,
  extension: null,
  description: "",
  proof_text: "",
  confirmed_by: null,
  checklist_items: [],
  comments: [],
  reminders: null,
  actions: ["comment"],
  last_nudged_at: null,
  readings: [FRIDGE],
  readings_taken: [],
  recheck_until: null,
  ...overrides,
});

function stub(routes: Record<string, () => Response>): string[] {
  const urls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string) => {
      urls.push(String(input));
      const path = String(input).replace("/api/v1/owner/companies/1/", "").split("?")[0]!;
      return routes[path]?.() ?? json({ detail: "Not found." }, 404);
    }),
  );
  return urls;
}

const mounted: Array<{ unmount: () => void }> = [];

async function openDrawer(task: TaskDetail, language: "en" | "uz" = "en") {
  stub({ "tasks/7/": () => json(task), "tasks/options/": () => json({ people: [], positions: [], routines: [], policies: [] }) });
  const app = await testApp("/c/1/tasks?task=7", language);
  const { wrapper } = mountWithProviders(TaskDrawer, { plugins: app.plugins });
  mounted.push(wrapper);
  await flushPromises();
  await flushPromises();
  return document.body.querySelector("[data-testid=readings]");
}

async function mountWidget(body: ReadingsToday | null) {
  const urls = stub(body ? { "routines/readings/today/": () => json(body) } : {});
  const app = await testApp("/c/1");
  const { wrapper } = mountWithProviders(ReadingsTodayWidget, { plugins: app.plugins, props: { companyId: 1 } });
  mounted.push(wrapper);
  await flushPromises();
  await flushPromises();
  return { wrapper, urls };
}

const today = (overrides: Partial<ReadingsToday> = {}): ReadingsToday => ({ day: "2026-10-23", set_up: true, taken: 6, excursions: [], missed: [], ...overrides });

beforeEach(() => {
  mergeModuleMessages("tasks", { en, ru, uz });
});

afterEach(() => {
  mounted.splice(0).forEach((wrapper) => wrapper.unmount());
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("readings helpers", () => {
  const number = (value: string | number | null | undefined, decimals = 0) => formatNumber(value, "uz", decimals);

  it("write ranges and values the way the reader writes numbers", () => {
    expect(rangeText("2.0", "8.0", "°C", number)).toBe("2–8 °C");
    expect(rangeText(null, "60.0", "%", number)).toBe("≤ 60 %");
    expect(rangeText("15.5", null, "°C", number)).toBe("≥ 15,5 °C");
    expect(rangeText(null, null, "°C", number)).toBe("");
    expect(valueText("5.20", "°C", number)).toBe("5,2 °C");
    expect(valueText("-3.50", "°C", number)).toBe("−3,5 °C");
  });

  it("group a task's values by spec, oldest first, and know when the latest is still out", () => {
    const recheck = taken({ id: 2, value: "5.40", in_range: true, is_recheck: true, note: "", recorded_at: "2026-10-23T15:40:00Z" });
    const groups = readingGroups([FRIDGE, HUMIDITY], [recheck, taken()]);
    expect(groups.map((group) => group.key)).toEqual(["t", "h"]);
    expect(groups[0]!.values.map((value) => value.id)).toEqual([1, 2]);
    expect(groups[0]!.open).toBe(false);
    expect(groups[1]!.values).toEqual([]);
    expect(readingGroups([FRIDGE], [taken()])[0]!.open).toBe(true);
    // A key only the values know (a spec renamed since) still shows, with the reading's own words.
    expect(readingGroups([], [taken({ key: "x", label: "Old fridge" })])[0]!.label).toBe("Old fridge");
  });
});

describe("the drawer's Readings section", () => {
  it("shows each spec's range and the values: state, who, when, the note and the recheck", async () => {
    const section = await openDrawer(
      detail({
        readings_taken: [taken(), taken({ id: 2, value: "5.40", in_range: true, is_recheck: true, note: "", recorded_at: "2026-10-23T15:40:00Z" })],
      }),
    );
    expect(section).not.toBeNull();
    const text = section!.textContent ?? "";
    expect(text).toContain("Fridge 2 temperature");
    expect(text).toContain("Allowed: 2–8 °C");
    expect(text).toContain("Critical");
    const values = [...section!.querySelectorAll("[data-testid=reading-value]")];
    expect(values.map((value) => value.getAttribute("data-in-range"))).toEqual(["false", "true"]);
    expect(values[0]!.textContent).toContain("8.9 °C");
    expect(values[0]!.textContent).toContain("Out of range");
    expect(values[0]!.textContent).toContain("“The door was left open: vaccines moved to fridge 1”");
    expect(values[0]!.textContent).toContain("Alisher Valiyev");
    expect(values[0]!.className).toContain("bg-danger-soft");
    expect(values[1]!.textContent).toContain("5.4 °C");
    expect(values[1]!.textContent).toContain("In range");
    expect(values[1]!.textContent).toContain("Recheck");
    // Back in range: no "a recheck may come" line.
    expect(section!.querySelector("[data-testid=recheck-until]")).toBeNull();
  });

  it("says until when a recheck may come while a value is still out of range", async () => {
    const section = await openDrawer(detail({ readings_taken: [taken()], recheck_until: "2099-10-23T17:05:00Z" }));
    expect(section!.querySelector("[data-testid=recheck-until]")?.textContent).toContain("A recheck may come until");
  });

  it("lists what an open run asks for before anything is taken, in Uzbek with a decimal comma", async () => {
    const section = await openDrawer(
      detail({ status: "todo", completed_at: null, readings: [{ ...FRIDGE, min: "2.5" }, HUMIDITY] }),
      "uz",
    );
    const text = section!.textContent ?? "";
    expect(text).toContain("Ruxsat etilgan: 2,5–8 °C");
    expect(text).toContain("Ruxsat etilgan: ≤ 60 %");
    expect(section!.querySelectorAll("[data-reading]")).toHaveLength(2);
    expect(text).toContain("Hali o‘lchanmagan");
  });

  it("isn't there for a task without readings", async () => {
    expect(await openDrawer(detail({ proof: "photo", readings: [], readings_taken: [] }))).toBeNull();
  });
});

describe("the Overview card of today's readings", () => {
  it("is registered for those who see everyone's work", () => {
    expect(module.widgets?.find((widget) => widget.id === "tasks.readings_today")).toMatchObject({ kind: "card", span: 2, perm: "tasks.view_all" });
  });

  it("lists an excursion with its note and a missed reading, each opening its routine", async () => {
    const { wrapper, urls } = await mountWidget(
      today({
        excursions: [{ ...taken(), task_id: 7, day: "2026-10-23", time: "20:05", branch: { id: 2, name: "Yunusobod", code: "YNS" }, routine: { id: 40, title: "Fridge 2: temperature, 20:00" }, back_in_range_at: null }],
        missed: [{ task_id: 9, routine: { id: 41, title: "Room: temperature and humidity, 20:00" }, branch: { id: 1, name: "Chilonzor", code: "CHL" }, due_at: "2026-10-23T15:00:00Z", assignee: null }],
      }),
    );
    expect(urls.some((url) => url.includes("/routines/readings/today/"))).toBe(true);
    const excursions = wrapper.find("[data-testid=readings-excursions]");
    expect(excursions.text()).toContain("Fridge 2 temperature 8.9 °C");
    expect(excursions.text()).toContain("Allowed: 2–8 °C");
    expect(excursions.text()).toContain("“The door was left open: vaccines moved to fridge 1”");
    expect(excursions.text()).toContain("Yunusobod");
    expect(excursions.find("a").attributes("href")).toBe("/c/1/routines/40");
    const missed = wrapper.find("[data-testid=readings-missed]");
    expect(missed.text()).toContain("Room: temperature and humidity, 20:00");
    expect(missed.text()).toContain("Chilonzor");
    expect(missed.find("a").attributes("href")).toBe("/c/1/routines/41");
    // Both still need someone: the count says 2.
    expect(wrapper.find("[data-testid=readings-today]").text()).toContain("2");
  });

  it("says when a recheck brought a value back, and leaves it out of the count", async () => {
    const { wrapper } = await mountWidget(
      today({
        excursions: [{ ...taken(), task_id: 7, day: "2026-10-23", time: "20:05", branch: null, routine: { id: 40, title: "Fridge 2" }, back_in_range_at: "2026-10-23T15:40:00Z" }],
      }),
    );
    expect(wrapper.find("[data-testid=back-in-range]").text()).toMatch(/^Back in range at \d{2}:\d{2}$/);
    expect(wrapper.findComponent({ name: "UiBadge" }).exists()).toBe(false);
  });

  it("reads calm when every reading is in range", async () => {
    const { wrapper } = await mountWidget(today());
    expect(wrapper.text()).toContain("All readings in range");
    expect(wrapper.text()).toContain("Taken today: 6");
  });

  it("renders nothing for a company that never set readings up, or an older backend", async () => {
    for (const body of [today({ set_up: false }), null]) {
      const { wrapper } = await mountWidget(body);
      expect(wrapper.find("[data-testid=readings-today]").exists()).toBe(false);
      expect(wrapper.text()).toBe("");
    }
  });
});
