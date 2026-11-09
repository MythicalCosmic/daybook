// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { toasts } from "@/components/useToast";
import { mergeModuleMessages } from "@/i18n";
import { useSessionStore } from "@/stores/session";
import { company, json, me } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import { attendanceKeys, downloadReport, getReport } from "../api";
import en from "../i18n/en.json";
import module from "../index";
import ReportsPage from "../pages/ReportsPage.vue";
import { rankingEnds, rateTone, reportFileName, sortRows } from "../reports";
import type { DepartmentReport, PeopleReport, PunctualityReport, RankingRow, ReportEmployee, ReportFigures, TrendDay, TrendReport } from "../types";

// jsdom has no ResizeObserver, and the charts measure themselves after a test can be done.
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

interface Call {
  method: string;
  url: string;
  headers: Record<string, string>;
}

function stubApi(routes: Record<string, (call: Call) => Response | Promise<Response>>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const call = { method: init?.method ?? "GET", url: input, headers: (init?.headers ?? {}) as Record<string, string> };
      calls.push(call);
      const path = input.replace("/api/v1/owner/companies/1/", "").split("?")[0]!;
      const handler = routes[`${call.method} ${path}`];
      return handler ? handler(call) : json({ detail: "Not found." }, 404);
    }),
  );
  return calls;
}

const figures = (overrides: Partial<ReportFigures> = {}): ReportFigures => ({
  days_scheduled: 20,
  days_present: 19,
  days_absent: 1,
  days_leave: 0,
  days_excused: 0,
  worked_minutes: 9120,
  late_count: 2,
  late_minutes: 35,
  early_leave_count: 1,
  early_leave_minutes: 20,
  overtime_minutes: 45,
  arrivals: 19,
  on_time: 17,
  punctuality_percent: 89.5,
  attendance_percent: 95,
  ...overrides,
});

const person = (id: number, name: string, extra: Partial<ReportEmployee> = {}): ReportEmployee => ({
  id,
  name,
  photo_url: null,
  position: { id: 1, name: "Operator" },
  department: { id: 3, name: "Sales" },
  branch: { id: 1, name: "Chilonzor" },
  ...extra,
});

const base = {
  range: { from: "2026-11-01", to: "2026-11-30" },
  counted_until: "2026-11-10",
  today: "2026-11-10",
};

const peopleReport = (): PeopleReport => ({
  ...base,
  totals: { people: 2, ...figures({ days_scheduled: 16, days_present: 15, days_absent: 1, late_count: 3, late_minutes: 52, arrivals: 15, on_time: 12, punctuality_percent: 80, attendance_percent: 93.8, worked_minutes: 7200 }) },
  rows: [
    { employee: person(7, "Aziz Rahimov"), ...figures({ days_scheduled: 8, days_present: 8, days_absent: 0, late_count: 0, late_minutes: 0, punctuality_percent: 100, attendance_percent: 100 }) },
    { employee: person(8, "Madina Saidova", { department: null }), ...figures({ days_scheduled: 8, days_present: 7, days_absent: 1, late_count: 3, late_minutes: 52, punctuality_percent: 57.1, attendance_percent: 87.5 }) },
  ],
});

const day = (date: string, extra: Partial<TrendDay> = {}): TrendDay => ({
  date,
  scheduled: 2,
  present: 2,
  expected_present: 2,
  late: 0,
  absent: 0,
  leave: 0,
  excused: 0,
  worked_minutes: 960,
  punctuality_percent: 100,
  ...extra,
});

const trendReport = (): TrendReport => ({
  ...base,
  totals: peopleReport().totals,
  days: [day("2026-11-09", { late: 1, punctuality_percent: 50 }), day("2026-11-10", { present: 1, scheduled: 2 })],
});

const rank = (rankNo: number, employee: ReportEmployee, extra: Partial<RankingRow> = {}): RankingRow => ({
  rank: rankNo,
  employee,
  punctuality_percent: 100,
  arrivals: 8,
  on_time: 8,
  late_count: 0,
  late_minutes: 0,
  average_late_minutes: 0,
  days_present: 8,
  ...extra,
});

const punctualityReport = (): PunctualityReport => ({
  ...base,
  totals: peopleReport().totals,
  average: 80,
  rows: [
    rank(1, person(7, "Aziz Rahimov")),
    rank(2, person(8, "Madina Saidova"), { punctuality_percent: 57.1, on_time: 4, arrivals: 7, late_count: 3, late_minutes: 52, average_late_minutes: 17 }),
  ],
});

const departmentReport = (): DepartmentReport => ({
  ...base,
  totals: peopleReport().totals,
  rows: [
    { department: { id: 3, name: "Sales" }, people: 1, ...figures() },
    { department: null, people: 1, ...figures({ punctuality_percent: 57.1 }) },
  ],
});

function reportRoutes(overrides: Record<string, () => Response> = {}) {
  return {
    "GET attendance/reports/summary/": () => json(peopleReport()),
    "GET attendance/reports/trend/": () => json(trendReport()),
    "GET attendance/reports/punctuality/": () => json(punctualityReport()),
    "GET attendance/reports/departments/": () => json(departmentReport()),
    "GET departments/": () => json([{ id: 3, name: "Sales", parent_id: null, path: ["Sales"] }]),
    ...overrides,
  };
}

async function openPage(path = "/c/1/attendance/reports", routes = reportRoutes()) {
  const calls = stubApi(routes);
  const app = await testApp(path);
  const { wrapper } = mountWithProviders(ReportsPage, { plugins: app.plugins });
  await flushPromises();
  await flushPromises();
  return { calls, app, wrapper };
}

beforeEach(() => {
  mergeModuleMessages("attendance", { en, ru: en, uz: en });
  toasts.splice(0, toasts.length);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

describe("reports api", () => {
  it("asks each report for the period, with only the filters that are set", async () => {
    const calls = stubApi(reportRoutes());
    await getReport(1, "summary", { from: "2026-11-01", to: "2026-11-30", branch: [1, 2], department: [] });
    await getReport(1, "punctuality", { from: "2026-11-01", to: "2026-11-10", department: [3, 4] });
    expect(calls.map((c) => c.url)).toEqual([
      "/api/v1/owner/companies/1/attendance/reports/summary/?from=2026-11-01&to=2026-11-30&branch=1&branch=2",
      "/api/v1/owner/companies/1/attendance/reports/punctuality/?from=2026-11-01&to=2026-11-10&department=3&department=4",
    ]);
    expect(attendanceKeys.report(4, "trend", { from: "2026-11-01", to: "2026-11-30" })).toEqual([4, "attendance", "report", { kind: "trend", from: "2026-11-01", to: "2026-11-30" }]);
  });

  it("downloads a report file under the name the server gives", async () => {
    const names: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      names.push(this.download);
    });
    URL.createObjectURL = vi.fn(() => "blob:report");
    URL.revokeObjectURL = vi.fn();
    const calls = stubApi({
      "GET attendance/reports/summary/": () =>
        new Response("xlsx", { status: 200, headers: { "Content-Disposition": "attachment; filename=\"report.xlsx\"; filename*=UTF-8''Davomat%20noyabr.xlsx" } }),
    });
    const name = await downloadReport(1, "summary", { from: "2026-11-01", to: "2026-11-30", branch: [2] }, "xlsx");
    expect(name).toBe("Davomat noyabr.xlsx");
    expect(names).toEqual(["Davomat noyabr.xlsx"]);
    expect(calls[0]!.url).toBe("/api/v1/owner/companies/1/attendance/reports/summary/?from=2026-11-01&to=2026-11-30&branch=2&format=xlsx");
    // A file, not JSON: the server picks the type from ?format.
    expect(calls[0]!.headers.Accept).toBe("*/*");
  });
});

describe("report helpers", () => {
  it("reads the file name from Content-Disposition", () => {
    expect(reportFileName('attachment; filename="davomat-2026-11.pdf"', "x.pdf")).toBe("davomat-2026-11.pdf");
    expect(reportFileName("attachment; filename*=UTF-8''%D0%9E%D1%82%D1%87%D1%91%D1%82.xlsx", "x.xlsx")).toBe("Отчёт.xlsx");
    expect(reportFileName('attachment; filename="../../etc/passwd"', "x")).toBe("..-..-etc-passwd");
    expect(reportFileName(null, "attendance-summary.xlsx")).toBe("attendance-summary.xlsx");
    expect(reportFileName("attachment", "fallback.pdf")).toBe("fallback.pdf");
  });

  it("tones rates and splits the ranking without showing anyone twice", () => {
    expect([rateTone(96), rateTone(80), rateTone(40), rateTone(null)]).toEqual(["success", "warning", "danger", "neutral"]);
    const rows = [1, 2, 3, 4, 5, 6, 7].map((n) => rank(n, person(n, `P${n}`), { punctuality_percent: 100 - n * 5, late_count: n > 5 ? n : 0 }));
    const { best, worst } = rankingEnds(rows, 3);
    expect(best.map((row) => row.employee.name)).toEqual(["P1", "P2", "P3"]);
    expect(worst.map((row) => row.employee.name)).toEqual(["P7", "P6"]); // the least punctual first
    // A small team: the late person shows once, under "needs attention".
    const small = rankingEnds([rank(1, person(1, "A")), rank(2, person(2, "B"), { late_count: 1, punctuality_percent: 80 })]);
    expect(small.best.map((row) => row.employee.name)).toEqual(["A"]);
    expect(small.worst.map((row) => row.employee.name)).toEqual(["B"]);
  });

  it("sorts rows by a field either way, empty values last", () => {
    const rows = [{ v: 2 }, { v: null }, { v: 9 }];
    const value = (row: { v: number | null }) => row.v;
    expect(sortRows(rows, "v", value).map((row) => row.v)).toEqual([2, 9, null]);
    expect(sortRows(rows, "-v", value).map((row) => row.v)).toEqual([9, 2, null]);
  });
});

describe("the module", () => {
  it("serves the reports after the timesheet, with a command", () => {
    const keys = module.nav?.map((item) => item.key) ?? [];
    expect(keys.indexOf("reports")).toBe(keys.indexOf("timesheet") + 1);
    const route = module.routes.find((r) => r.path === "attendance/reports");
    expect(route).toMatchObject({ name: "attendance.reports", meta: { title: "attendance.nav.reports", perm: "attendance.view" } });
  });
});

describe("ReportsPage", () => {
  it("shows this month's strip, trend, ranking and everyone's figures", async () => {
    const { calls, wrapper } = await openPage();
    const summary = calls.find((c) => c.url.includes("/reports/summary/"));
    expect(summary?.url).toMatch(/from=\d{4}-\d{2}-01&to=\d{4}-\d{2}-\d{2}/);
    const text = document.body.textContent ?? "";
    expect(text).toContain("Attendance rate");
    expect(text).toContain("93.8%");
    expect(text).toContain("Punctuality");
    expect(text).toContain("12 of 15 arrivals on time");
    // The ranking: the most punctual and who needs attention, each once.
    expect(document.querySelector("[data-ranking=best]")?.textContent).toContain("Aziz Rahimov");
    expect(document.querySelector("[data-ranking=worst]")?.textContent).toContain("Madina Saidova");
    expect(document.querySelector("[data-ranking=worst]")?.textContent).toContain("Late 3 times");
    expect(document.querySelector("[data-ranking=best]")?.textContent).not.toContain("Madina Saidova");
    expect(text).toContain("Madina Saidova");
    expect(document.querySelector("[data-report-footnote]")?.textContent).toContain("Counted until");
    wrapper.unmount();
  });

  it("switches the table to departments, asking for them only then", async () => {
    const { calls, app, wrapper } = await openPage();
    expect(calls.some((c) => c.url.includes("/reports/departments/"))).toBe(false);
    await app.router.push("/c/1/attendance/reports?view=departments");
    await flushPromises();
    await flushPromises();
    expect(calls.some((c) => c.url.includes("/reports/departments/"))).toBe(true);
    const text = document.body.textContent ?? "";
    expect(text).toContain("Sales");
    expect(text).toContain("No department");
    wrapper.unmount();
  });

  it("downloads the table it shows as Excel", async () => {
    const names: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      names.push(this.download);
    });
    URL.createObjectURL = vi.fn(() => "blob:report");
    URL.revokeObjectURL = vi.fn();
    const routes = reportRoutes();
    const { calls, wrapper } = await openPage("/c/1/attendance/reports", {
      ...routes,
      "GET attendance/reports/summary/": () => json(peopleReport()),
    });
    const trigger = document.querySelector<HTMLButtonElement>("[data-report-export]");
    expect(trigger).not.toBeNull();
    trigger!.click();
    await flushPromises();
    // The table on the page is listed first.
    expect(document.querySelector("[data-report-kind]")?.getAttribute("data-report-kind")).toBe("summary");
    // The file: the same endpoint with ?format.
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string) => {
        calls.push({ method: "GET", url: input, headers: {} });
        return new Response("x", { status: 200, headers: { "Content-Disposition": 'attachment; filename="davomat.xlsx"' } });
      }),
    );
    document.querySelector<HTMLButtonElement>('[data-format="summary.xlsx"]')!.click();
    await flushPromises();
    await flushPromises();
    expect(calls.at(-1)?.url).toContain("/attendance/reports/summary/?");
    expect(calls.at(-1)?.url).toContain("format=xlsx");
    expect(names).toEqual(["davomat.xlsx"]);
    wrapper.unmount();
  });

  it("hides the export from people without data.export", async () => {
    stubApi(reportRoutes());
    const app = await testApp("/c/1/attendance/reports");
    useSessionStore().me = me([company({ is_owner: false, role: { id: 4, name: "Viewer" }, permissions: ["attendance.view", "dashboard.access"] })]);
    const { wrapper } = mountWithProviders(ReportsPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    expect(document.querySelector("[data-report-export]")).toBeNull();
    // Nor the department filter: listing departments needs members.view.
    expect(document.body.textContent).not.toContain("All departments");
    expect(document.body.textContent).toContain("Aziz Rahimov");
    wrapper.unmount();
  });

  it("says when nobody has shifts, and what to do with an empty period", async () => {
    const noShifts = peopleReport();
    noShifts.totals = { ...noShifts.totals, days_scheduled: 0, days_absent: 0, punctuality_percent: null, attendance_percent: null };
    const first = await openPage("/c/1/attendance/reports", reportRoutes({ "GET attendance/reports/summary/": () => json(noShifts) }));
    expect(document.querySelector("[data-report-no-shifts]")?.textContent).toContain("No shifts are planned");
    first.wrapper.unmount();
    document.body.innerHTML = "";

    const empty: PeopleReport = { ...peopleReport(), rows: [], totals: { people: 0, ...figures({ days_scheduled: 0, days_present: 0, days_absent: 0, late_count: 0, arrivals: 0, on_time: 0, worked_minutes: 0, punctuality_percent: null, attendance_percent: null }) } };
    const second = await openPage("/c/1/attendance/reports", reportRoutes({ "GET attendance/reports/summary/": () => json(empty) }));
    expect(document.querySelector("[data-report-empty]")?.textContent).toContain("No attendance in this period");
    expect(document.body.textContent).toContain("Set work schedules");
    second.wrapper.unmount();
  });
});
