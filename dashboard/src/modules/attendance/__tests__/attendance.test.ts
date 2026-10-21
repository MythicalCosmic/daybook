// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { toasts } from "@/components/useToast";
import { mergeModuleMessages, setLanguage } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import {
  attendanceKeys,
  bulkRoster,
  createShift,
  decideCorrection,
  decideSwap,
  editRecord,
  getBoard,
  getRoster,
  getTimesheet,
  listRecords,
  publishRoster,
  updateShift,
} from "../api";
import BoardTile from "../components/BoardTile.vue";
import ShiftGrid from "../components/ShiftGrid.vue";
import en from "../i18n/en.json";
import module from "../index";
import { clockOf, compactTime, formatDistance, hours, localDateTime, shiftMonth, spanMinutes, weekdayIndex } from "../lib";
import SwapsPage from "../pages/SwapsPage.vue";
import type { BoardRow, Roster, Shift, Swap } from "../types";

interface Call {
  method: string;
  url: string;
  body: unknown;
}

function stubApi(routes: Record<string, (call: Call) => Response | Promise<Response>>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const call = { method: init?.method ?? "GET", url: input, body: init?.body ? JSON.parse(String(init.body)) : undefined };
      calls.push(call);
      const path = input.replace("/api/v1/owner/companies/1/", "").split("?")[0]!;
      const handler = routes[`${call.method} ${path}`];
      return handler ? handler(call) : json({ detail: "Not found." }, 404);
    }),
  );
  return calls;
}

beforeEach(() => {
  mergeModuleMessages("attendance", { en, ru: en, uz: en });
  toasts.splice(0, toasts.length);
});

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

const shift = (id: number, memberId: number | null, date: string, extra: Partial<Shift> = {}): Shift => ({
  id,
  member_id: memberId,
  date,
  starts_at: `${date}T09:00:00+05:00`,
  ends_at: `${date}T18:00:00+05:00`,
  start: "09:00",
  end: "18:00",
  break_minutes: 60,
  minutes: 480,
  branch: { id: 1, name: "Chilonzor", code: "CHL" },
  position: null,
  status: memberId ? "planned" : "open",
  source: "schedule",
  published: true,
  note: "",
  time_off_id: null,
  swap_pending: false,
  has_record: false,
  ...extra,
});

const roster = (): Roster => ({
  week: "2026-10-19",
  days: ["2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24", "2026-10-25"],
  holidays: {},
  members: [
    {
      id: 7,
      name: "Alisher Valiyev",
      photo_url: null,
      position: { id: 1, name: "Sales floor" },
      home_branch: { id: 1, name: "Chilonzor" },
      status: "approved",
      schedule: { id: 3, name: "Savdo zali 6/1" },
      minutes: 960,
      leave: ["2026-10-23"],
    },
    {
      id: 8,
      name: "Madina Saidova",
      photo_url: null,
      position: { id: 2, name: "Cashier" },
      home_branch: { id: 1, name: "Chilonzor" },
      status: "approved",
      schedule: null,
      minutes: 0,
      leave: [],
    },
  ],
  shifts: [shift(1, 7, "2026-10-21"), shift(2, 7, "2026-10-22", { published: false, source: "manual" }), shift(3, null, "2026-10-24")],
  unpublished: 1,
  coverage: {},
  templates: [{ id: 5, name: "Morning", starts_at: "09:00", ends_at: "18:00", break_minutes: 60, color: 1, position_id: null, order: 0, is_active: true }],
});

describe("api", () => {
  it("calls the plan's endpoints with the right params and bodies", async () => {
    const calls = stubApi({
      "GET attendance/board/": () => json({ people: [] }),
      "GET attendance/records/": () => json({ count: 0, next: null, previous: null, results: [] }),
      "PATCH attendance/records/4/": () => json({}),
      "GET attendance/timesheet/": () => json({}),
      "GET attendance/roster/": () => json({}),
      "POST attendance/shifts/": () => json({}, 201),
      "PATCH attendance/shifts/9/": () => json({}),
      "POST attendance/shifts/bulk/": () => json({ count: 3 }),
      "POST attendance/shifts/publish/": () => json({ count: 2 }),
      "POST attendance/swaps/5/approve/": () => json({}),
      "POST attendance/swaps/5/reject/": () => json({}),
      "POST attendance/corrections/6/decide/": () => json({}),
    });
    await getBoard(1, { date: "2026-10-20", branch: [1, 2] });
    await listRecords(1, { from: "2026-10-01", overtime: "pending", branch: [] });
    await editRecord(1, 4, { check_out_at: "2026-10-20T19:30", reason: "Inventory" });
    await getTimesheet(1, { month: "2026-10", branch: null });
    await getRoster(1, { week: "2026-10-19", branch: 2 });
    await createShift(1, { member_id: null, date: "2026-10-24", start: "12:00", end: "21:00", branch_id: 1 });
    await updateShift(1, 9, { member_id: 8, date: "2026-10-22" });
    expect((await bulkRoster(1, { action: "copy_week", week: "2026-10-26" })).count).toBe(3);
    expect((await publishRoster(1, { start: "2026-10-26", end: "2026-11-01" })).count).toBe(2);
    await decideSwap(1, 5, true);
    await decideSwap(1, 5, false, "We need you");
    await decideCorrection(1, 6, false, "You left at 18:02");
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
      "GET /api/v1/owner/companies/1/attendance/board/?date=2026-10-20&branch=1&branch=2",
      "GET /api/v1/owner/companies/1/attendance/records/?from=2026-10-01&overtime=pending",
      "PATCH /api/v1/owner/companies/1/attendance/records/4/",
      "GET /api/v1/owner/companies/1/attendance/timesheet/?month=2026-10",
      "GET /api/v1/owner/companies/1/attendance/roster/?week=2026-10-19&branch=2",
      "POST /api/v1/owner/companies/1/attendance/shifts/",
      "PATCH /api/v1/owner/companies/1/attendance/shifts/9/",
      "POST /api/v1/owner/companies/1/attendance/shifts/bulk/",
      "POST /api/v1/owner/companies/1/attendance/shifts/publish/",
      "POST /api/v1/owner/companies/1/attendance/swaps/5/approve/",
      "POST /api/v1/owner/companies/1/attendance/swaps/5/reject/",
      "POST /api/v1/owner/companies/1/attendance/corrections/6/decide/",
    ]);
    expect(calls[2]!.body).toEqual({ check_out_at: "2026-10-20T19:30", reason: "Inventory" });
    expect(calls[5]!.body).toMatchObject({ member_id: null, start: "12:00", branch_id: 1 });
    expect(calls[10]!.body).toEqual({ reason: "We need you" });
    expect(calls[11]!.body).toEqual({ approve: false, reason: "You left at 18:02" });
  });

  it("keys every query under the company and the module", () => {
    expect(attendanceKeys.board(4, { date: null, branch: [] })).toEqual([4, "attendance", "board", { date: null, branch: [] }]);
    expect(attendanceKeys.all(4)).toEqual([4, "attendance"]);
  });

  it("registers as the catalog says, with widgets, a settings panel, a person tab and badges", () => {
    expect(module).toMatchObject({ id: "attendance", group: "people", order: 20, hotkey: "a", perm: "attendance.view", feature: "attendance" });
    expect(module.widgets?.map((w) => w.id)).toEqual(["attendance.kpi.present", "attendance.strip"]);
    expect(module.settings?.map((s) => s.id)).toEqual(["attendance"]);
    expect(module.personTabs?.map((tab) => tab.id)).toEqual(["attendance"]);
    expect(module.badge?.({ counters: { "attendance.not_in": 2 }, versions: {} })).toBe(2);
    const swaps = module.nav?.find((item) => item.key === "swaps");
    expect(swaps?.badge?.({ counters: { "attendance.swaps": 3 }, versions: {} })).toBe(3);
    expect(module.deepLinks?.roster?.("2026-10-26")).toBe("attendance/roster?week=2026-10-26");
  });
});

describe("lib", () => {
  it("does the hour arithmetic the pages show", () => {
    expect(spanMinutes("09:00", "18:00", 60)).toBe(480);
    expect(spanMinutes("22:00", "06:00", 0)).toBe(480);
    expect(hours(480)).toBe("8");
    expect(hours(495)).toBe("8.3");
    expect(clockOf("2026-10-21T08:57:00+05:00")).toBe("08:57");
    expect(localDateTime("2026-10-20", "02:00", "22:00")).toBe("2026-10-21T02:00");
    expect(localDateTime("2026-10-20", "18:30", "09:00")).toBe("2026-10-20T18:30");
    expect(shiftMonth("2026-12", 1)).toBe("2027-01");
    expect(weekdayIndex("2026-10-21")).toBe(2);
    expect(formatDistance(1234, { m: "m", km: "km" })).toBe("1.2 km");
    expect(formatDistance(34, { m: "m", km: "km" })).toBe("34 m");
    // Uzbek and Russian write the decimal comma.
    for (const language of ["ru", "uz"] as const) {
      void setLanguage(language);
      expect(hours(495)).toBe("8,3");
      expect(hours(480)).toBe("8");
      expect(formatDistance(1234, { m: "m", km: "km" })).toBe("1,2 km");
    }
    void setLanguage("en");
    // Schedule cards keep the half hours.
    expect(compactTime("08:30")).toBe("8:30");
    expect(compactTime("17:30:00")).toBe("17:30");
    expect(compactTime("09:00")).toBe("9:00");
  });
});

describe("BoardTile", () => {
  const row = (extra: Partial<BoardRow> = {}): BoardRow => ({
    member: { id: 7, name: "Alisher Valiyev", photo_url: null, position: { id: 1, name: "Sales floor" }, home_branch: null, status: "approved" },
    branch: { id: 1, name: "Chilonzor", code: "CHL" },
    state: "late",
    reason: null,
    shift: shift(1, 7, "2026-10-21"),
    record: {
      id: 11,
      member_id: 7,
      shift_id: 1,
      date: "2026-10-21",
      status: "open",
      check_in_at: "2026-10-21T09:25:00+05:00",
      check_out_at: null,
      in_lat: "41.29",
      in_lng: "69.2",
      in_accuracy_m: 12,
      in_distance_m: 1240,
      out_lat: null,
      out_lng: null,
      out_accuracy_m: null,
      out_distance_m: null,
      branch: { id: 1, name: "Chilonzor", code: "CHL" },
      in_source: "app",
      out_source: "",
      late_minutes: 25,
      early_leave_minutes: 0,
      worked_minutes: 0,
      overtime_minutes: 0,
      overtime_status: "none",
      is_late: true,
      flags: ["outside_geofence"],
      note: "",
      has_photo: false,
    },
    ...extra,
  });

  it("shows the trust signals of a check-in and opens it", async () => {
    const app = await testApp("/c/1/attendance");
    const { wrapper, inner } = mountWithProviders(BoardTile, { props: { row: row() }, plugins: app.plugins });
    const text = wrapper.text();
    expect(text).toContain("In since 09:25");
    expect(text).toContain("1.2 km");
    expect(text).toContain("+25m");
    await wrapper.find("button").trigger("click");
    expect(inner.emitted("open")?.[0]).toEqual([row()]);
  });

  it("says why someone is off", async () => {
    const app = await testApp("/c/1/attendance");
    const { wrapper } = mountWithProviders(BoardTile, { props: { row: row({ state: "off", reason: "leave", record: null }) }, plugins: app.plugins });
    expect(wrapper.text()).toContain("On leave");
  });

  it("leads with the shift's hours and says how late someone not here yet is", async () => {
    const app = await testApp("/c/1/attendance");
    const late = row({ state: "not_yet", reason: "late", record: null });
    const { wrapper } = mountWithProviders(BoardTile, { props: { row: late, now: "2026-10-21T09:40:00+05:00" }, plugins: app.plugins });
    const text = wrapper.text();
    expect(text.indexOf("09:00–18:00")).toBeLessThan(text.indexOf("Sales floor"));
    expect(text).toContain("Shift started 09:00");
    expect(text).toContain("+40m");
    // A past day has no "now": no lateness is made up.
    const past = mountWithProviders(BoardTile, { props: { row: late, now: null }, plugins: app.plugins });
    expect(past.wrapper.text()).not.toContain("+40m");
  });
});

// The map's own tests (names as text, picker) are in components/__tests__/MapView.test.ts.

describe("ShiftGrid", () => {
  function transfer(data: Record<string, string>) {
    const store = { ...data };
    return {
      dataTransfer: {
        setData: (type: string, value: string) => (store[type] = value),
        getData: (type: string) => store[type] ?? "",
        effectAllowed: "move",
      },
    };
  }

  async function grid(editable = true) {
    const app = await testApp("/c/1/attendance/roster");
    return mountWithProviders(ShiftGrid, { props: { roster: roster(), editable, today: "2026-10-21" }, plugins: app.plugins });
  }

  it("draws drafts, open shifts and leave", async () => {
    const { wrapper } = await grid();
    expect(wrapper.findAll(".att-draft").length).toBeGreaterThanOrEqual(1);
    expect(wrapper.text()).toContain("Open shifts");
    expect(wrapper.text()).toContain("On leave");
  });

  it("moves a dragged shift to another person and day", async () => {
    const { wrapper, inner } = await grid();
    const cells = wrapper.findAll("[role=gridcell]");
    // Rows: open shifts (7 cells), Alisher (7), Madina (7). Madina on Thursday is cell 14 + 3.
    await cells[14 + 3]!.trigger("drop", transfer({ "application/x-attendance-shift": "1" }));
    expect(inner.emitted("move")?.[0]?.[1]).toEqual({ memberId: 8, date: "2026-10-22" });
  });

  it("places a dropped template and refuses past days", async () => {
    const { wrapper, inner } = await grid();
    const cells = wrapper.findAll("[role=gridcell]");
    await cells[7 + 4]!.trigger("drop", transfer({ "application/x-attendance-template": "5" }));
    expect(inner.emitted("place")?.[0]?.[1]).toEqual({ memberId: 7, date: "2026-10-23" });
    await cells[7 + 0]!.trigger("drop", transfer({ "application/x-attendance-template": "5" }));
    expect(inner.emitted("place")).toHaveLength(1);
  });

  it("adds on an empty day and edits on a chip; read-only without the permission", async () => {
    const { wrapper, inner } = await grid();
    await wrapper.find("button[aria-label^='Add a shift for Madina']").trigger("click");
    expect(inner.emitted("add")?.[0]?.[0]).toMatchObject({ memberId: 8 });
    await wrapper.findAll(".att-chip")[0]!.trigger("click");
    expect(inner.emitted("edit")).toHaveLength(1);
    const readonly = await grid(false);
    expect(readonly.wrapper.find(".att-add").exists()).toBe(false);
  });
});

describe("SwapsPage", () => {
  const swap = (id: number): Swap => ({
    id,
    kind: "cover",
    status: "accepted",
    shift: shift(10 + id, 7, "2026-10-24"),
    other_shift: null,
    requested_by: { id: 7, name: "Alisher Valiyev" },
    target: { id: 9, name: "Bekzod Mirzayev" },
    accepted_by: { id: 9, name: "Bekzod Mirzayev" },
    note: "Sister's wedding",
    decision_note: "",
    expires_at: "2026-10-24T09:00:00+05:00",
    created_at: "2026-10-20T09:00:00+05:00",
    decided_at: null,
  });

  it("approves in place: the swap leaves at once and comes back on refusal", async () => {
    const calls = stubApi({
      "GET attendance/swaps/": () => json({ count: 2, next: null, previous: null, results: [swap(1), swap(2)] }),
      "POST attendance/swaps/1/approve/": () => json({ ...swap(1), status: "approved" }),
      "POST attendance/swaps/2/approve/": () => json({ detail: "This shift has already started." }, 400),
    });
    const app = await testApp("/c/1/attendance/swaps");
    const { wrapper } = mountWithProviders(SwapsPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    expect(wrapper.text()).toContain("Bekzod Mirzayev covers Alisher Valiyev");
    const approve = () => wrapper.findAll("button").filter((b) => b.text() === "Approve");
    expect(approve()).toHaveLength(2);
    await approve()[0]!.trigger("click");
    await flushPromises();
    expect(calls.some((c) => c.method === "POST" && c.url.endsWith("swaps/1/approve/"))).toBe(true);
    expect(toasts.at(-1)?.title).toContain("Approved");
  });
});
