// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { VueQueryPlugin } from "@tanstack/vue-query";
import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";

import type { PermissionInfo } from "@/api/types";
import { PERMS } from "@/core/perms.generated";
import { i18n, mergeModuleMessages, setLanguage } from "@/i18n";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import { approveRequest, listPeople, offboardPerson, peopleKeys, rejectRequest, reorderPositions, suspendPerson, updatePerson, updateRole } from "../api";
import PermissionMatrix from "../components/PermissionMatrix.vue";
import en from "../i18n/en.json";
import ru from "../i18n/ru.json";
import uz from "../i18n/uz.json";
import module from "../index";
import { PERMISSION_AREAS, groupByArea, permissionArea } from "../permissionAreas";
import { bookedDaysAhead, rateTone, statusChip, tenureParts } from "../status";
import type { Role } from "../types";

interface Call {
  method: string;
  url: string;
  body: unknown;
}

function stub(respond: (call: Call) => Response = () => json({})): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const call = { method: init?.method ?? "GET", url: input, body: init?.body ? JSON.parse(String(init.body)) : undefined };
      calls.push(call);
      return respond(call);
    }),
  );
  return calls;
}

const role = (overrides: Partial<Role>): Role => ({
  id: 1,
  name: "Employee",
  permissions: [],
  is_owner: false,
  is_default: false,
  members_count: 3,
  can_edit: true,
  can_assign: true,
  ...overrides,
});

const permissions: PermissionInfo[] = [
  { code: "members.view", label: "View members", group: "members" },
  { code: "members.approve", label: "Approve join requests", group: "members" },
  { code: "finance.view", label: "View finance", group: "finance" },
] as PermissionInfo[];

beforeEach(() => {
  mergeModuleMessages("people", { en, ru, uz });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
  setLanguage("en");
});

describe("api", () => {
  it("calls the people endpoints with their filters and bodies", async () => {
    const calls = stub();
    await listPeople(1, { status: "current", branch: ["2", "3"], q: "Ali", page: 1, page_size: 50 });
    await updatePerson(1, 5, { role_id: 4, branch_ids: [2], home_branch_id: 2 });
    await suspendPerson(1, 5, { until: "2026-10-30", reason: "Kassa tekshiruvi" });
    await offboardPerson(1, 5, { terminated_on: "2026-10-21", reason: "resignation", note: "", steps: {}, override_blockers: false });
    await approveRequest(1, 7, { role_id: 4, position_id: null, branch_ids: [2], home_branch_id: 2 });
    await rejectRequest(1, 8, "Not hiring");
    await updateRole(1, 4, { permissions: ["members.view"] });
    await reorderPositions(1, [3, 1, 2]);
    expect(calls.map((c) => `${c.method} ${c.url.replace("/api/v1/owner/companies/1/", "")}`)).toEqual([
      "GET people/?status=current&branch=2&branch=3&q=Ali&page=1&page_size=50",
      "PATCH people/5/",
      "POST people/5/suspend/",
      "POST people/5/offboard/",
      "POST join-requests/7/approve/",
      "POST join-requests/8/reject/",
      "PATCH roles/4/",
      "POST positions/reorder/",
    ]);
    expect(calls[2]!.body).toEqual({ until: "2026-10-30", reason: "Kassa tekshiruvi" });
    expect(calls[3]!.body).toMatchObject({ terminated_on: "2026-10-21", reason: "resignation", override_blockers: false });
    expect(calls[5]!.body).toEqual({ reason: "Not hiring" });
    expect(calls[7]!.body).toEqual({ ids: [3, 1, 2] });
  });

  it("registers behind members.view with the members pulse keys", () => {
    expect(module).toMatchObject({ id: "people", group: "people", perm: "members.view", hotkey: "p" });
    expect(module.invalidates).toEqual(expect.arrayContaining(["members", "timeoff.time_off"]));
    expect(module.nav?.map((item) => item.to)).toEqual(["people", "people/requests", "people/roles", "people/positions"]);
    expect(peopleKeys.list(1, { page: 1 })).toEqual([1, "people", "list", { page: 1 }]);
  });
});

describe("status", () => {
  const day = (value: string) => `day ${value}`;

  it("puts the lifecycle first, then time off, then today's attendance", () => {
    expect(statusChip({ status: "suspended", suspended_until: "2026-10-26", fields: {} }, day)).toMatchObject({ tone: "warning", key: "people.status.suspendedUntil", params: { date: "day 2026-10-26" } });
    expect(statusChip({ status: "suspended", suspended_until: null, fields: {} }, day).key).toBe("people.status.suspended");
    expect(statusChip({ status: "approved", suspended_until: null, fields: { time_off_today: { id: 3, until: "2026-10-22" }, attendance_today: "in" } }, day)).toMatchObject({ key: "people.status.onLeave", avatar: "off" });
    expect(statusChip({ status: "approved", suspended_until: null, fields: { attendance_today: "late" } }, day).key).toBe("people.status.late");
    expect(statusChip({ status: "approved", suspended_until: null, fields: {} }, day).key).toBe("people.status.active");
    expect(statusChip({ status: "left", suspended_until: null, fields: {} }, day).key).toBe("people.status.left");
  });

  it("colours on-time rates and splits tenure", () => {
    expect([rateTone("95.0"), rateTone(80), rateTone("50"), rateTone(null)]).toEqual(["success", "warning", "danger", "neutral"]);
    expect(tenureParts(400)).toEqual({ years: 1, months: 1, days: 400 });
    expect(tenureParts(null)).toBeNull();
  });

  it("speaks Russian plurals with three forms and Uzbek with one", () => {
    setLanguage("ru");
    expect([1, 3, 5, 21].map((n) => i18n.global.t("people.days", { n }, n))).toEqual(["1 день", "3 дня", "5 дней", "21 день"]);
    setLanguage("uz");
    expect(i18n.global.t("people.days", { n: 5 }, 5)).toBe("5 kun");
    setLanguage("en");
    expect([0, 1, 2].map((n) => i18n.global.t("people.days", { n }, n))).toEqual(["0 days", "1 day", "2 days"]);
  });
});

describe("PermissionMatrix", () => {
  async function mountMatrix(roles: Role[], grantable: (code: string) => boolean) {
    const app = await testApp("/c/1/people/roles");
    return mountWithProviders(PermissionMatrix, { plugins: app.plugins, props: { roles, permissions, grantable, draft: {} } });
  }

  it("locks the Owner column, greys out what the editor can't grant and stages changes", async () => {
    const roles = [role({ id: 1, name: "Owner", is_owner: true, can_edit: false }), role({ id: 2, name: "Manager", permissions: ["members.view"] }), role({ id: 3, name: "Cashier", can_edit: false })];
    const { wrapper, inner } = await mountMatrix(roles, (code) => code !== "finance.view");
    await flushPromises();
    const text = wrapper.text();
    // Areas follow the sidebar, not the code prefix.
    expect(text).toContain("Team and attendance");
    expect(text).toContain("Finance");
    // Owner holds everything: its counts are full and it has no checkboxes.
    expect(wrapper.findAll('[aria-label="Owners hold every permission"]').length).toBe(3);
    const box = (name: string) => wrapper.find(`[aria-label="${name}"] [role="checkbox"]`);
    expect(box("Manager: View members").attributes("aria-checked")).toBe("true");
    expect(box("Manager: View finance").attributes("disabled")).toBeDefined();
    expect(box("Cashier: View members").attributes("disabled")).toBeDefined();

    await box("Manager: Approve join requests").trigger("click");
    const staged = inner.emitted("update:draft")!.at(-1)![0] as Record<number, string[]>;
    expect(staged).toEqual({ 2: ["members.view", "members.approve"] });

    // Undoing a staged change leaves nothing staged.
    wrapper.unmount();
    const app = await testApp("/c/1/people/roles");
    const again = mountWithProviders(PermissionMatrix, { plugins: app.plugins, props: { roles, permissions, grantable: () => true, draft: staged } });
    await flushPromises();
    expect(again.wrapper.find('[aria-label="Manager: Approve join requests"] [role="checkbox"]').attributes("aria-checked")).toBe("true");
    await again.wrapper.find('[aria-label="Manager: Approve join requests"] [role="checkbox"]').trigger("click");
    expect(again.inner.emitted("update:draft")!.at(-1)![0]).toEqual({});
  });

  it("filters by area and search", async () => {
    const app = await testApp("/c/1/people/roles");
    const { wrapper } = mountWithProviders(PermissionMatrix, { plugins: app.plugins, props: { roles: [role({ id: 2 })], permissions, grantable: () => true, draft: {}, query: "approve" } });
    await flushPromises();
    expect(wrapper.text()).toContain("Approve join requests");
    expect(wrapper.text()).not.toContain("View finance");
    const empty = mountWithProviders(PermissionMatrix, { plugins: app.plugins, props: { roles: [role({ id: 2 })], permissions, grantable: () => true, draft: {}, area: "finance", query: "approve" } });
    await flushPromises();
    expect(empty.wrapper.text()).toContain("No permission matches.");
  });
});

describe("permission areas", () => {
  it("places every permission in exactly one area, each named in every language", () => {
    const placed = PERMISSION_AREAS.flatMap((area) => area.perms);
    expect([...placed].sort()).toEqual([...PERMS].sort());
    expect(new Set(placed).size).toBe(placed.length);
    for (const area of [...PERMISSION_AREAS.map((a) => a.id), "other"]) {
      for (const dictionary of [en, uz, ru] as Array<Record<string, string>>) expect(dictionary[`people.permArea.${area}`], area).toBeTruthy();
    }
    // Areas are not one-row leftovers of the code prefixes any more.
    expect(PERMISSION_AREAS.every((area) => area.perms.length >= 3)).toBe(true);
  });

  it("groups in sidebar order and keeps a new permission near its prefix", () => {
    const rows = [{ code: "finance.view" }, { code: "audit.view" }, { code: "members.view" }, { code: "company.settings" }, { code: "tasks.later_feature" }, { code: "brand.new" }];
    expect(groupByArea(rows).map((g) => [g.area, g.items.map((i) => i.code)])).toEqual([
      ["access", ["company.settings", "audit.view"]],
      ["people", ["members.view"]],
      ["work", ["tasks.later_feature"]],
      ["finance", ["finance.view"]],
      ["other", ["brand.new"]],
    ]);
    expect(permissionArea("time_off.approve")).toBe("people");
    expect(permissionArea("roles.manage")).toBe("access");
  });
});

describe("bookedDaysAhead", () => {
  it("counts approved days after today, which days off taken leaves out", () => {
    const today = "2026-10-21";
    expect(
      bookedDaysAhead(
        [
          { first_day: "2026-10-25", last_day: "2026-10-27", status: "approved" },
          // Started already: only the days after today.
          { first_day: "2026-10-20", last_day: "2026-10-22", status: "approved" },
          { first_day: "2026-10-28", last_day: "2026-10-29", status: "pending" },
          { first_day: "2026-10-19", last_day: "2026-10-21", status: "approved" },
        ],
        today,
      ),
    ).toBe(4);
    expect(bookedDaysAhead([], today)).toBe(0);
  });
});

describe("OffboardPage", () => {
  const person = {
    id: 7,
    name: "Madina Saidova",
    full_name: "Madina Saidova",
    first_name: "Madina",
    last_name: "Saidova",
    photo_url: null,
    phone: "+998901112233",
    username: "",
    position: { id: 3, name: "Cashier" },
    role: { id: 1, name: "Employee", is_owner: false },
    home_branch: { id: 1, name: "Chilonzor", code: "CHL" },
    branches: [{ id: 1, name: "Chilonzor", code: "CHL" }],
    status: "approved",
    suspended_until: null,
    joined_on: "2025-09-06",
    left_on: null,
    onboarded: true,
    bot_blocked: false,
    work: { on_time_30d: null, done_30d: 0, late_now: 0, open_now: 0 },
    fields: {},
    language: "uz",
    overview: {},
    can: {},
  };
  const preview = {
    today: "2026-10-21",
    reasons: ["resignation", "other"],
    can_override: false,
    blockers: 1,
    steps: [
      { key: "members", label: "Access and work", order: 10, lines: ["Their access ends at once."], blockers: [], fields: [], defaults: {} },
      { key: "sales", label: "Cash", order: 30, lines: [], blockers: ["Open till CHL-1042 must be closed first."], fields: [], defaults: {}, restricted: true },
    ],
  };

  it("shows a step the viewer can't open with its blocker, and only an owner may go ahead", async () => {
    const OffboardPage = (await import("../pages/OffboardPage.vue")).default;
    stub((call) => (call.url.endsWith("offboard-preview/") ? json(preview) : json(person)));
    const app = await testApp("/c/1/people/7/offboard");
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: "/c/:companyId/people/:memberId/offboard", component: OffboardPage },
        { path: "/:any(.*)*", component: { render: () => null } },
      ],
    });
    await router.push("/c/1/people/7/offboard");
    const { wrapper } = mountWithProviders(OffboardPage, { plugins: [app.pinia, router, i18n, [VueQueryPlugin, { queryClient: app.client }]] });
    await flushPromises();
    await flushPromises();

    await wrapper.find('[role="radio"]').trigger("click");
    await wrapper.findAll("button").find((b) => b.text() === "Continue")!.trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("Cash");
    expect(wrapper.text()).toContain("No access");
    expect(wrapper.text()).toContain("Open till CHL-1042 must be closed first.");
    expect(wrapper.text()).toContain("what blocks it still counts");
    await wrapper.findAll("button").find((b) => b.text() === "Continue")!.trigger("click");
    await flushPromises();
    const submit = wrapper.findAll("button").find((b) => b.text().startsWith("Offboard"))!;
    expect(submit.attributes("disabled")).toBeDefined();
    expect(wrapper.text()).toContain(en["people.offboard.onlyOwner"]);
  });
});
