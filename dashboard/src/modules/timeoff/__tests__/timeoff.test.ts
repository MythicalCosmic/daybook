// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mergeModuleMessages } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import { addPublicHolidays, decideTimeOff, getCalendar, listHolidays, listTimeOff, recordTimeOff, revokeTimeOff, timeOffKeys } from "../api";
import LeaveMonthGrid from "../components/LeaveMonthGrid.vue";
import en from "../i18n/en.json";
import module from "../index";
import type { CalendarMonth } from "../types";

interface Call {
  method: string;
  url: string;
  body: unknown;
}

function stub(): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const raw = init?.body;
      const body = raw instanceof FormData ? Object.fromEntries([...raw.entries()].map(([k, v]) => [k, typeof v === "string" ? v : `file:${(v as File).name}`])) : raw ? JSON.parse(String(raw)) : undefined;
      calls.push({ method: init?.method ?? "GET", url: input.replace("/api/v1/owner/companies/1/", ""), body });
      return json({});
    }),
  );
  return calls;
}

beforeEach(() => {
  mergeModuleMessages("timeoff", { en, ru: en, uz: en });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

describe("api", () => {
  it("calls the time-off endpoints, sending the sick note as a form only when there is one", async () => {
    const calls = stub();
    await listTimeOff(1, { status: ["pending"], ordering: "pending_first", page: 1, page_size: 25 });
    await decideTimeOff(1, 4, true);
    await decideTimeOff(1, 5, false);
    await recordTimeOff(1, { member_id: 9, first_day: "2026-10-20", last_day: "2026-10-21", reason: "Isitma" });
    await recordTimeOff(1, { member_id: 9, first_day: "2026-10-20", last_day: "2026-10-20", reason: "", attachment: new File(["%PDF"], "note.pdf", { type: "application/pdf" }) });
    await revokeTimeOff(1, 6, { reason: "Inventarizatsiya", from_day: "2026-10-23" });
    await getCalendar(1, { month: "2026-10", branch: [2, 3], everyone: true });
    await listHolidays(1, 2026);
    await addPublicHolidays(1, 2027);
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
      "GET time-off/?status=pending&ordering=pending_first&page=1&page_size=25",
      "POST time-off/4/approve/",
      "POST time-off/5/reject/",
      "POST time-off/record/",
      "POST time-off/record/",
      "POST time-off/6/revoke/",
      "GET time-off/calendar/?month=2026-10&branch=2&branch=3&everyone=true",
      "GET holidays/?year=2026",
      "POST holidays/public/",
    ]);
    expect(calls[3]!.body).toEqual({ member_id: 9, first_day: "2026-10-20", last_day: "2026-10-21", reason: "Isitma" });
    expect(calls[4]!.body).toEqual({ member_id: "9", first_day: "2026-10-20", last_day: "2026-10-20", reason: "", attachment: "file:note.pdf" });
    expect(calls[5]!.body).toEqual({ reason: "Inventarizatsiya", from_day: "2026-10-23" });
    expect(calls[8]!.body).toEqual({ year: 2027 });
  });

  it("registers for approvers and managers, with a Person 360 tab", () => {
    expect(module).toMatchObject({ id: "timeoff", group: "people", perm: ["time_off.approve", "time_off.manage"] });
    expect(module.invalidates).toEqual(["timeoff"]);
    expect(module.personTabs?.map((tab) => tab.id)).toEqual(["time-off"]);
    expect(timeOffKeys.calendar(1, { month: "2026-10" })).toEqual([1, "timeoff", "calendar", { month: "2026-10" }]);
  });
});

describe("LeaveMonthGrid", () => {
  const month: CalendarMonth = {
    month: "2026-10",
    from: "2026-10-01",
    to: "2026-10-31",
    today: "2026-10-21",
    holidays: [{ id: 1, date: "2026-10-01", name: "O‘qituvchi va murabbiylar kuni" }],
    workdays: [0, 1, 2, 3, 4, 5],
    rows: [
      {
        member: { id: 11, name: "Dilshod Karimov", photo_url: null },
        position: "Sales floor",
        home_branch: { id: 2, name: "Yunusobod", code: "YNS" },
        items: [
          { id: 101, first_day: "2026-10-19", last_day: "2026-10-23", status: "approved", reason: "Oilaviy to‘y", recorded: false, days: 5 },
          { id: 102, first_day: "2026-10-30", last_day: "2026-11-02", status: "pending", reason: "", recorded: false, days: 4 },
        ],
      },
      {
        member: { id: 12, name: "Madina Saidova", photo_url: null },
        position: "Cashier",
        home_branch: { id: 1, name: "Chilonzor", code: "CHL" },
        items: [{ id: 103, first_day: "2026-09-29", last_day: "2026-10-02", status: "approved", reason: "", recorded: true, days: 3 }],
      },
    ],
  };

  it("draws a bar per stretch, clipped to the month, and opens requests and people", async () => {
    const app = await testApp("/c/1/time-off");
    const { wrapper, inner } = mountWithProviders(LeaveMonthGrid, { plugins: app.plugins, props: { month, activeId: 101 } });
    await flushPromises();
    expect(wrapper.findAll('[role="columnheader"]').length).toBe(32);
    const bars = wrapper.findAll("button.leave");
    expect(bars.length).toBe(3);
    expect(bars[0]!.text()).toContain("Oilaviy to‘y");
    expect(bars[1]!.classes().join(" ")).toContain("pending");
    expect(bars[2]!.classes().join(" ")).toContain("recorded");
    // Starts before the month: the bar begins at day 1.
    expect(bars[2]!.attributes("style")).toContain("left: calc(0% + 2px)");
    await bars[0]!.trigger("click");
    expect(inner.emitted("open")).toEqual([[101]]);
    await wrapper.findAll("button").find((b) => b.text().includes("Madina Saidova"))!.trigger("click");
    expect(inner.emitted("person")).toEqual([[12]]);
  });
});
