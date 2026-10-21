// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import { agendaApi, agendaKeys } from "../api";
import AgendaList from "../components/AgendaList.vue";
import SourceToggles from "../components/SourceToggles.vue";
import en from "../i18n/en.json";
import module from "../index";
import { byPriority, eventIdOf, eventParam, monthChips, parseEventParam, remindKey, sourceColor, sourceLabel, sourceRank, toCalendarItem, tokenColor, windowFor } from "../lib";
import type { CalendarEntry } from "../types";

const entry = (overrides: Partial<CalendarEntry> = {}): CalendarEntry => ({
  id: "agenda.events:12",
  source: "agenda.events",
  kind: "agenda.event",
  title: "Weekly planning",
  start: "2026-10-26T09:00:00+05:00",
  end: "2026-10-26T09:30:00+05:00",
  all_day: false,
  color: "chart-3",
  url: "/c/1/calendar?event=12",
  ...overrides,
});

beforeEach(() => {
  mergeModuleMessages("agenda", { en, ru: en, uz: en });
});

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("lib", () => {
  it("turns colour tokens into CSS variables and ignores anything else, with a warning", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    expect(tokenColor("chart-3")).toBe("var(--c-chart-3)");
    expect(tokenColor("chart-8")).toBe("var(--c-chart-8)");
    expect(tokenColor("danger")).toBe("var(--c-danger)");
    expect(tokenColor("warning")).toBe("var(--c-warning)");
    expect(tokenColor("success")).toBe("var(--c-success)");
    expect(tokenColor("info")).toBe("var(--c-info)");
    expect(tokenColor("accent")).toBe("var(--c-primary)");
    expect(tokenColor("")).toBeNull();
    expect(warn).not.toHaveBeenCalled();
    expect(tokenColor("#c67139")).toBeNull();
    expect(tokenColor("#c67139")).toBeNull();
    expect(tokenColor("var(--c-danger)")).toBeNull();
    expect(tokenColor("constructor")).toBeNull();
    expect(warn).toHaveBeenCalledTimes(3);
    expect(String(warn.mock.calls[0]![0])).toContain("#c67139");
    // An item with a raw colour falls back to the calendar's colour for its kind.
    expect(toCalendarItem(entry({ color: "#ff0000" })).color).toBeNull();
    warn.mockRestore();
  });

  it("finds the company event behind an item, repeating or not", () => {
    expect(eventIdOf(entry())).toBe(12);
    expect(eventIdOf(entry({ id: "agenda.events:12-20261026" }))).toBe(12);
    expect(eventIdOf(entry({ kind: "timeoff.holiday", id: "timeoff.holidays:3" }))).toBeNull();
  });

  it("asks for the days each view needs", () => {
    expect(windowFor("month", "2026-10-21")).toEqual({ from: "2026-09-28", to: "2026-11-08" });
    expect(windowFor("week", "2026-10-21")).toEqual({ from: "2026-10-19", to: "2026-10-25" });
    expect(windowFor("agenda", "2026-10-21")).toEqual({ from: "2026-10-21", to: "2026-11-19" });
  });

  it("names reminders", () => {
    expect(remindKey(null)).toEqual({ key: "agenda.remind.none" });
    expect(remindKey(0)).toEqual({ key: "agenda.remind.atStart" });
    expect(remindKey(30)).toEqual({ key: "agenda.remind.minutes", n: 30 });
    expect(remindKey(120)).toEqual({ key: "agenda.remind.hours", n: 2 });
    expect(remindKey(4320)).toEqual({ key: "agenda.remind.days", n: 3 });
  });

  it("maps API items onto the calendar components", () => {
    expect(toCalendarItem(entry({ subtitle: "Office" }), "Company events")).toMatchObject({ id: "agenda.events:12", color: "var(--c-chart-3)", subtitle: "Office" });
    expect(toCalendarItem(entry({ source: "timeoff.holidays", kind: "timeoff.holiday" }), "Holidays").subtitle).toBe("Holidays");
  });

  it("names its own calendar in the UI language and keeps other sources' names", () => {
    const t = (key: string) => `«${key}»`;
    expect(sourceLabel({ key: "agenda.events", label: "Company events" }, t)).toBe("«agenda.sources.own»");
    expect(sourceLabel({ key: "timeoff.holidays", label: "Bayramlar" }, t)).toBe("Bayramlar");
  });

  it("orders a crowded day: company events first, shifts last, unknown calendars before the tasks", () => {
    const shifts = entry({ id: "attendance.shifts:1", source: "attendance.shifts", kind: "attendance.shift", title: "Chilonzor: 2 on shift", start: "2026-10-26", end: null, all_day: true });
    const tasks = entry({ id: "tasks.due:1", source: "tasks.due", kind: "tasks.due", title: "12 tasks due", start: "2026-10-26", end: null, all_day: true });
    const birthdays = entry({ id: "people.birthdays:1", source: "people.birthdays", kind: "people.birthday", title: "Aziz", start: "2026-10-26", end: null, all_day: true });
    const late = entry({ id: "agenda.events:13", title: "Stock count", start: "2026-10-26T15:00:00+05:00" });
    const early = entry({ id: "agenda.events:12", title: "Planning", start: "2026-10-26T09:00:00+05:00" });
    expect(byPriority([shifts, tasks, late, birthdays, early]).map((e) => e.id)).toEqual(["agenda.events:12", "agenda.events:13", "people.birthdays:1", "tasks.due:1", "attendance.shifts:1"]);
    expect(sourceRank("timeoff.holidays")).toBeLessThan(sourceRank("tasks.due"));
  });

  it("gives the month a labelled chip on every day of a long date, and timed dates their time", () => {
    const away = entry({ id: "timeoff.time_off:7", source: "timeoff.time_off", kind: "timeoff.time_off", title: "Aziz · time off", start: "2026-09-27", end: "2026-09-30", all_day: true });
    const meeting = entry({ id: "agenda.events:12-20260928", start: "2026-09-28T23:30:00+05:00", end: null });
    const { items, meta } = monthChips([away, meeting], { from: "2026-09-28", to: "2026-11-08" }, "Asia/Tashkent", (iso) => iso.slice(11, 16));

    // The meeting first (company events lead), on its company-local day, as an all-day chip with its time beside it.
    expect(items.map((item) => [item.id, item.start, item.all_day])).toEqual([
      ["agenda.events:12-20260928", "2026-09-28", true],
      ["timeoff.time_off:7@2026-09-28", "2026-09-28", true],
      ["timeoff.time_off:7@2026-09-29", "2026-09-29", true],
      ["timeoff.time_off:7@2026-09-30", "2026-09-30", true],
    ]);
    expect(meta.get("agenda.events:12-20260928")).toEqual({ time: "23:30", title: "Weekly planning", origin: "agenda.events:12-20260928" });
    expect(meta.get("timeoff.time_off:7@2026-09-29")).toEqual({ time: null, title: "Aziz · time off", origin: "timeoff.time_off:7" });
    expect(items[1]!.color).toBe("var(--c-chart-3)");
  });

  it("colours each calendar's chip by its own colour, else by most of its dates", () => {
    const debts = [entry({ source: "finance.debts_due", color: "danger" }), entry({ source: "finance.debts_due", color: "danger" }), entry({ source: "finance.debts_due", color: "success" })];
    expect(sourceColor("finance.debts_due", debts)).toBe("var(--c-danger)");
    expect(sourceColor("tasks.due", [entry({ source: "tasks.due", color: "danger" })])).toBe("var(--c-primary)");
    expect(sourceColor("projects.milestones", [])).toBeNull();
  });

  it("opens a repeating event on the occurrence that was clicked", () => {
    expect(eventParam(entry({ id: "agenda.events:12-20261027" }))).toBe("12-20261027");
    expect(eventParam(entry())).toBe("12");
    expect(eventParam(entry({ kind: "timeoff.holiday", id: "timeoff.holidays:3" }))).toBeNull();
    expect(parseEventParam("12-20261027")).toEqual({ id: 12, day: "2026-10-27" });
    expect(parseEventParam("12")).toEqual({ id: 12, day: null });
    expect(parseEventParam("x")).toBeNull();
    expect(parseEventParam("0")).toBeNull();
  });
});

describe("api", () => {
  it("asks for the window and sends events and answers", async () => {
    const calls: Array<{ method: string; url: string; body: unknown }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string, init?: RequestInit) => {
        calls.push({ method: init?.method ?? "GET", url: input, body: init?.body ? JSON.parse(String(init.body)) : undefined });
        return json({});
      }),
    );
    await agendaApi.calendar(1, { from: "2026-10-19", to: "2026-10-25" });
    await agendaApi.respond(1, 12, "declined");
    await agendaApi.cancel(1, 12, "Moved");
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
      "GET /api/v1/owner/companies/1/calendar/?from=2026-10-19&to=2026-10-25",
      "POST /api/v1/owner/companies/1/calendar/events/12/respond/",
      "POST /api/v1/owner/companies/1/calendar/events/12/cancel/",
    ]);
    expect(calls[1]!.body).toEqual({ response: "declined" });
    expect(calls[2]!.body).toEqual({ reason: "Moved" });
    expect(agendaKeys.calendar(3, "a", "b")).toEqual([3, "agenda", "calendar", { from: "a", to: "b" }]);
  });

  it("registers as the catalog says", () => {
    expect(module).toMatchObject({ id: "agenda", group: "comms", order: 30, hotkey: "c" });
    expect(module.widgets?.map((w) => w.id)).toEqual(["agenda.upcoming"]);
    expect(module.invalidates).toContain("agenda");
    expect(module.deepLinks?.event?.("7")).toBe("calendar?event=7");
  });
});

describe("components", () => {
  it("toggles a calendar off and on", async () => {
    const app = await testApp("/c/1/calendar");
    const { inner } = mountWithProviders(SourceToggles, {
      props: {
        modelValue: [],
        sources: [
          { key: "agenda.events", label: "Company events" },
          { key: "timeoff.holidays", label: "Holidays" },
        ],
        counts: { "agenda.events": 4 },
        colors: { "agenda.events": "var(--c-chart-3)", "timeoff.holidays": "var(--c-danger)" },
      },
      plugins: app.plugins,
    });
    await inner.findAll("button")[1]!.trigger("click");
    expect(inner.emitted("update:modelValue")?.[0]).toEqual([["timeoff.holidays"]]);
    expect(inner.text()).toContain("Company events");
    expect(inner.text()).toContain("4");
  });

  it("lists the agenda by day and opens an item", async () => {
    const app = await testApp("/c/1/calendar");
    const items = [
      toCalendarItem(entry({ id: "agenda.events:1", start: "2026-10-22T15:00:00+05:00", end: "2026-10-22T17:00:00+05:00", title: "Kassa trening" })),
      toCalendarItem(entry({ id: "timeoff.holidays:2", kind: "timeoff.holiday", start: "2026-10-24", end: null, all_day: true, title: "Holiday", color: "danger" })),
    ];
    const { inner } = mountWithProviders(AgendaList, { props: { anchor: "2026-10-21", items }, plugins: app.plugins });
    await flushPromises();
    const text = inner.text();
    expect(text).toContain("Kassa trening");
    expect(text).toContain("15:00 – 17:00");
    expect(text).toContain("All day");
    await inner.findAll("button").find((b) => b.text().includes("Holiday"))!.trigger("click");
    expect(inner.emitted("item-click")?.[0]?.[0]).toMatchObject({ id: "timeoff.holidays:2" });
  });
});
