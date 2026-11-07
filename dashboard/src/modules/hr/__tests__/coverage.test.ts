// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { extensionsFor } from "@/core/extensions";
import type { Perm } from "@/core/perms";
import { mergeModuleMessages } from "@/i18n";
import { useSessionStore } from "@/stores/session";
import { company, json, me } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import { hrApi } from "../api";
import PharmacistsEditor from "../components/PharmacistsEditor.vue";
import RosterCoverage from "../components/RosterCoverage.vue";
import { allGaps, coverageTotals, daySegments, hoursOf, levelsFor, rosterLink, weekParams } from "../coverage";
import en from "../i18n/en.json";
import module from "../index";
import CoveragePage from "../pages/CoveragePage.vue";
import type { Coverage, CoverageBranch, Pharmacists } from "../types";

interface Call {
  method: string;
  url: string;
  body: unknown;
}

function stub(routes: Record<string, unknown> = {}): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const url = input.replace("/api/v1/owner/companies/1/", "");
      calls.push({ method: init?.method ?? "GET", url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      const match = Object.keys(routes)
        .sort((a, b) => b.length - a.length)
        .find((prefix) => url.startsWith(prefix));
      return json(match ? routes[match] : {});
    }),
  );
  return calls;
}

beforeEach(() => {
  mergeModuleMessages("hr", { en, ru: en, uz: en });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

/** Yunusobod around the clock, Monday 9 to Sunday 15 November 2026: Saturday night has no qualified pharmacist. */
function yunusobod(): CoverageBranch {
  const days = Array.from({ length: 7 }, (_, index) => {
    const date = `2026-11-${String(9 + index).padStart(2, "0")}`;
    const next = `2026-11-${String(10 + index).padStart(2, "0")}`;
    return { date, opens: `${date}T00:00:00+05:00`, closes: `${next}T00:00:00+05:00`, closed: null, shifts: [], gaps: [] } as CoverageBranch["days"][number];
  });
  const saturday = days[5]!;
  saturday.gaps = [{ branch_id: 2, start: "2026-11-14T20:00:00+05:00", end: "2026-11-15T00:00:00+05:00", minutes: 240, have: 0, need: 1 }];
  saturday.shifts = [
    {
      shift_id: 7,
      member: { id: 31, name: "Dilshod Karimov" },
      position: "Farmatsevt",
      start: "2026-11-14T20:00:00+05:00",
      end: "2026-11-15T08:00:00+05:00",
      published: true,
      counts: false,
      reason: "unverified",
      kinds: ["pharmacist_certificate"],
    },
  ];
  days[6]!.gaps = [{ branch_id: 2, start: "2026-11-15T00:00:00+05:00", end: "2026-11-15T08:00:00+05:00", minutes: 480, have: 0, need: 1 }];
  return {
    branch: { id: 2, name: "Yunusobod", code: "YNS" },
    open_24h: true,
    opens_at: null,
    closes_at: null,
    days,
    gaps: [{ branch_id: 2, start: "2026-11-14T20:00:00+05:00", end: "2026-11-15T08:00:00+05:00", minutes: 720, have: 0, need: 1 }],
    shifts: 14,
    gap_minutes: 720,
  };
}

const coverage = (branches: CoverageBranch[], state: Coverage["state"] = "ok"): Coverage => ({ state, start: "2026-11-09", end: "2026-11-15", need: 1, drafts: false, branches });

describe("helpers", () => {
  it("splits a day's open window into covered and uncovered stretches", () => {
    const day = { opens: "2026-11-14T08:00:00+05:00", closes: "2026-11-14T22:00:00+05:00", gaps: [{ branch_id: 1, start: "2026-11-14T17:00:00+05:00", end: "2026-11-14T22:00:00+05:00", minutes: 300, have: 0, need: 1 }] };
    expect(daySegments(day)).toEqual([
      { from: 0, to: 9 / 14, tone: "covered" },
      { from: 9 / 14, to: 1, tone: "gap" },
    ]);
    expect(daySegments({ ...day, gaps: [{ ...day.gaps[0]!, have: 1, need: 2 }] })[1]!.tone).toBe("short");
    expect(daySegments({ ...day, gaps: [] })).toEqual([{ from: 0, to: 1, tone: "covered" }]);
    expect(daySegments({ opens: null, closes: null, gaps: [] })).toEqual([]);
  });

  it("knows the week, the roster link, the hours and the levels", () => {
    expect(weekParams("2026-11-12", 2, true)).toEqual({ from: "2026-11-09", to: "2026-11-15", branch: [2], drafts: true });
    expect(weekParams("2026-11-09")).toEqual({ from: "2026-11-09", to: "2026-11-15" });
    expect(rosterLink(1, 2, "2026-11-14")).toBe("/c/1/attendance/roster?branch=2&week=2026-11-09");
    expect([hoursOf(300), hoursOf(90), hoursOf(720)]).toEqual([5, 1.5, 12]);
    expect(levelsFor("pharmacy_diploma")).toEqual(["higher", "college"]);
    expect(levelsFor("qualification_category")).toEqual(["highest", "first", "second"]);
    expect(levelsFor("pharmacist_certificate")).toEqual([]);
    const totals = coverageTotals([yunusobod()]);
    expect(totals).toEqual({ branches: 1, gaps: 1, minutes: 720, short: 1 });
    expect(allGaps([yunusobod()]).map((gap) => gap.branchName)).toEqual(["Yunusobod"]);
  });

  it("calls the coverage endpoints", async () => {
    const calls = stub();
    await hrApi.coverage(1, weekParams("2026-11-09", 2, true));
    await hrApi.liveCoverage(1);
    await hrApi.pharmacists(1);
    await hrApi.savePharmacists(1, [{ id: 4, role: "head" }, { id: 5, role: null }]);
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
      "GET hr/coverage/?from=2026-11-09&to=2026-11-15&branch=2&drafts=true",
      "GET hr/coverage/live/",
      "GET hr/coverage/pharmacists/",
      "POST hr/coverage/pharmacists/",
    ]);
    expect(calls[3]!.body).toEqual({ positions: [{ id: 4, role: "head" }, { id: 5, role: null }] });
  });

  it("registers the page, the roster slot and the Overview card", () => {
    expect(module.routes.find((route) => route.path === "hr/coverage")?.meta?.perm).toEqual(["hr.view", "attendance.view"]);
    expect(module.extensions?.["attendance.roster.coverage"]).toHaveLength(1);
    expect(module.widgets?.map((widget) => widget.id)).toEqual(["hr.coverage_week"]);
    expect(module.deepLinks?.coverage?.("2")).toBe("hr/coverage?branch=2");
    // Whoever runs the roster sees the slot; with HR off, nobody does.
    const roster = company({ is_owner: false, permissions: ["attendance.view"] as Perm[] });
    expect(extensionsFor("attendance.roster.coverage", roster).map((entry) => entry.moduleId)).toContain("hr");
    expect(extensionsFor("attendance.roster.coverage", { ...roster, features: ["attendance"] })).toEqual([]);
  });
});

describe("the roster slot", () => {
  async function mountSlot(body: Coverage, perms: Perm[] = []) {
    const calls = stub({ "hr/coverage/": body });
    const app = await testApp("/c/1/attendance/roster");
    if (perms.length) useSessionStore().me = me([company({ is_owner: false, permissions: perms })]);
    const { wrapper } = mountWithProviders(RosterCoverage, { plugins: app.plugins, props: { context: { companyId: 1, branchId: 2, week: "2026-11-09" } } });
    await flushPromises();
    await flushPromises();
    return { wrapper, calls };
  }

  it("lists the week's gaps, drafts counted", async () => {
    const { wrapper, calls } = await mountSlot(coverage([yunusobod()]));
    expect(calls[0]!.url).toBe("hr/coverage/?from=2026-11-09&to=2026-11-15&branch=2&drafts=true");
    const list = wrapper.find("[data-gap-list]");
    expect(list.text()).toContain("20:00–08:00");
    expect(wrapper.text()).toContain("1 gap without a qualified pharmacist (12 h)");
  });

  it("says the week is covered, and stays silent while the rule is off", async () => {
    const covered = yunusobod();
    covered.gaps = [];
    for (const day of covered.days) day.gaps = [];
    const first = await mountSlot(coverage([covered]));
    expect(first.wrapper.find("[data-covered]").exists()).toBe(true);
    first.wrapper.unmount();

    const off = await mountSlot(coverage([], "off"));
    expect(off.wrapper.text()).toBe("");
  });

  it("prompts HR to set it up, and nobody else", async () => {
    const hr = await mountSlot(coverage([], "setup"), ["hr.view", "hr.manage"]);
    expect(hr.wrapper.text()).toContain(en["hr.coverage.slot.setupTitle"]);
    hr.wrapper.unmount();
    const roster = await mountSlot(coverage([], "setup"), ["attendance.view"]);
    expect(roster.wrapper.text()).toBe("");
  });
});

describe("the coverage page", () => {
  it("draws each pharmacy's week, why someone doesn't count, and links to the roster", async () => {
    stub({ "hr/coverage/live/": { state: "ok", at: "2026-11-09T10:00:00+05:00", gaps: [] }, "hr/coverage/": coverage([yunusobod()]) });
    const app = await testApp("/c/1/hr/coverage?week=2026-11-09");
    const { wrapper } = mountWithProviders(CoveragePage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    const branch = wrapper.find("[data-coverage-branch='2']");
    expect(branch.exists()).toBe(true);
    expect(branch.text()).toContain("Yunusobod");
    expect(branch.text()).toContain("1 gap · 12 h");
    const saturday = branch.find("[data-day='2026-11-14']");
    expect(saturday.find("[data-day-gaps]").text()).toContain("20:00–00:00");
    expect(saturday.text()).toContain("Dilshod Karimov");
    expect(saturday.text()).toContain(`${en["hr.coverage.reason.unverified"]}: ${en["hr.kind.pharmacist_certificate"]}`);
    expect(branch.find("[data-fix-roster]").attributes("href")).toBe("/c/1/attendance/roster?branch=2&week=2026-11-09");
  });

  it("shows a pharmacy open right now without a qualified pharmacist", async () => {
    stub({
      "hr/coverage/live/": { state: "ok", at: "2026-11-09T20:30:00+05:00", gaps: [{ branch: { id: 2, name: "Yunusobod", code: "YNS" }, since: "2026-11-09T20:00:00+05:00", minutes: 30, have: 0, need: 1, checked_in: [{ id: 31, name: "Dilshod Karimov" }] }] },
      "hr/coverage/": coverage([yunusobod()]),
    });
    const app = await testApp("/c/1/hr/coverage");
    const { wrapper } = mountWithProviders(CoveragePage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    const alert = wrapper.find("[data-live-gaps]");
    expect(alert.text()).toContain("No qualified pharmacist at Yunusobod right now");
    expect(alert.text()).toContain("Checked in: Dilshod Karimov");
  });
});

describe("who counts as a pharmacist", () => {
  const pharmacists: Pharmacists = {
    positions: [
      { position: { id: 4, name: "Dorixona mudiri" }, role: null, people: 2, required: [] },
      { position: { id: 5, name: "Farmatsevt" }, role: "pharmacist", people: 6, required: [{ kind: "pharmacy_diploma", level: "", alternatives: [] }, { kind: "pharmacist_certificate", level: "", alternatives: [] }] },
    ],
  };

  it("lists the positions with what they ask for, and saves only what changed", async () => {
    const calls = stub({ "hr/coverage/pharmacists/": pharmacists });
    const app = await testApp("/c/1/settings/hr");
    const { wrapper } = mountWithProviders(PharmacistsEditor, { plugins: app.plugins });
    await flushPromises();
    expect(wrapper.find("[data-position='5']").text()).toContain(`${en["hr.kind.pharmacy_diploma"]} · ${en["hr.kind.pharmacist_certificate"]}`);
    expect(wrapper.find("[data-save-pharmacists]").attributes("disabled")).toBeDefined();

    const editor = wrapper.findComponent(PharmacistsEditor);
    (editor.vm as unknown as { $: { setupState: { choices: Record<number, string> } } }).$.setupState.choices[4] = "head";
    await flushPromises();
    await wrapper.find("[data-save-pharmacists]").trigger("click");
    await flushPromises();
    const saved = calls.find((call) => call.method === "POST");
    expect(saved?.body).toEqual({ positions: [{ id: 4, role: "head" }] });
  });
});
