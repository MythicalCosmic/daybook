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
import { eventIdOf, remindKey, toCalendarItem, tokenColor, windowFor } from "../lib";
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
  it("turns colour tokens into CSS and passes anything else through", () => {
    expect(tokenColor("chart-3")).toBe("var(--c-chart-3)");
    expect(tokenColor("danger")).toBe("var(--c-danger)");
    expect(tokenColor("")).toBeNull();
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
    expect(toCalendarItem(entry(), "Company events")).toMatchObject({ id: "agenda.events:12", color: "var(--c-chart-3)", subtitle: "Company events" });
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
