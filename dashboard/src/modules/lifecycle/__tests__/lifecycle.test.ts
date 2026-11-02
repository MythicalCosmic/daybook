// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { VueQueryPlugin } from "@tanstack/vue-query";
import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";

import type { Company } from "@/api/types";
import type { Perm } from "@/core/perms";
import { i18n, mergeModuleMessages } from "@/i18n";
import peopleEn from "@/modules/people/i18n/en.json";
import { useSessionStore } from "@/stores/session";
import { company, json, me } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import { lifecycleApi, lifecycleKeys } from "../api";
import ProfileActions from "../components/ProfileActions.vue";
import en from "../i18n/en.json";
import module from "../index";
import { lifecycleAccess, nextStep, recordFormErrors, recordParams, recordPayload, recordState, type RecordForm } from "../lib";

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
  mergeModuleMessages("lifecycle", { en, ru: en, uz: en });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

const form = (overrides: Partial<RecordForm> = {}): RecordForm => ({
  member: 9,
  kind: "written_warning",
  category: "storage_breach",
  incident_on: "2026-11-01",
  description: "  Insulin muzlatgichdan tashqarida qolgan.  ",
  files: [],
  proposeFine: false,
  fine: null,
  ...overrides,
});

describe("discipline create payload", () => {
  it("sends the fine only when proposing one with an amount above zero", () => {
    expect(recordPayload(form())).toEqual({ member_id: 9, kind: "written_warning", category: "storage_breach", incident_on: "2026-11-01", description: "Insulin muzlatgichdan tashqarida qolgan." });
    expect(recordPayload(form({ proposeFine: true, fine: "200000.00" })).fine_amount).toBe("200000.00");
    // An amount typed and then switched off is not sent; a zero amount is not a fine.
    expect(recordPayload(form({ proposeFine: false, fine: "200000.00" }))).not.toHaveProperty("fine_amount");
    expect(recordPayload(form({ proposeFine: true, fine: "0.00" }))).not.toHaveProperty("fine_amount");
  });

  it("adds the evidence file when there is one", () => {
    const file = new File(["x"], "termometr.jpg", { type: "image/jpeg" });
    expect(recordPayload(form({ files: [file] })).evidence).toBe(file);
  });

  it("names what is missing or wrong", () => {
    expect(recordFormErrors(form(), "2026-11-02")).toEqual({});
    expect(recordFormErrors(form({ member: null, category: null, incident_on: null, description: " " }), "2026-11-02")).toEqual({
      member: "required",
      category: "required",
      incident_on: "required",
      description: "required",
    });
    expect(recordFormErrors(form({ incident_on: "2026-11-03" }), "2026-11-02")).toEqual({ incident_on: "future" });
    expect(recordFormErrors(form({ proposeFine: true, fine: null }), "2026-11-02")).toEqual({ fine: "amount" });
    expect(recordFormErrors(form({ proposeFine: true, fine: "-5000.00" }), "2026-11-02")).toEqual({ fine: "amount" });
  });
});

describe("records", () => {
  it("reads a record's state: issued, read, withdrawn, or no longer counting once it expired", () => {
    expect(recordState({ status: "issued", active: true })).toBe("issued");
    expect(recordState({ status: "acknowledged", active: true })).toBe("acknowledged");
    expect(recordState({ status: "acknowledged", active: false })).toBe("expired");
    expect(recordState({ status: "withdrawn", active: false })).toBe("withdrawn");
  });

  it("suggests the next step from the strongest record of the last six months", () => {
    const today = "2026-11-02";
    const rec = (kind: "verbal_warning" | "written_warning" | "final_warning" | "reprimand" | "other", incident_on: string, active = true) => ({ kind, incident_on, active });
    expect(nextStep([], today)).toBeNull();
    expect(nextStep([rec("verbal_warning", "2026-10-20")], today)).toEqual({ step: "written_warning", count: 1 });
    expect(nextStep([rec("verbal_warning", "2026-10-20"), rec("written_warning", "2026-09-01")], today)).toEqual({ step: "final_warning", count: 2 });
    expect(nextStep([rec("reprimand", "2026-08-01")], today)).toEqual({ step: "final_warning", count: 1 });
    expect(nextStep([rec("final_warning", "2026-06-01")], today)).toEqual({ step: "consider_termination", count: 1 });
    // Older than six months, no longer counting (withdrawn or expired), or "other": nothing counts.
    expect(nextStep([rec("final_warning", "2026-04-30"), rec("written_warning", "2026-10-01", false), rec("other", "2026-10-30")], today)).toBeNull();
  });

  it("turns the filters into the API's params", () => {
    expect(recordParams({ kind: ["written_warning"], category: "storage_breach", status: [], active: true }, " Alisher ")).toEqual({
      kind: ["written_warning"],
      category: ["storage_breach"],
      active: true,
      q: "Alisher",
    });
    expect(recordParams({}, "")).toEqual({});
  });

  it("reads who may do what", () => {
    const grant = (perms: string[]) => (perm: string) => perms.includes(perm);
    expect(lifecycleAccess(grant(["hr.view"]))).toEqual({ view: true, discipline: false, suspend: false });
    expect(lifecycleAccess(grant(["hr.discipline"]))).toEqual({ view: true, discipline: true, suspend: false });
    expect(lifecycleAccess(grant(["hr.suspend"]))).toEqual({ view: true, discipline: false, suspend: true });
    expect(lifecycleAccess(grant([]))).toEqual({ view: false, discipline: false, suspend: false });
  });
});

describe("api", () => {
  it("calls the lifecycle endpoints, sending evidence as a form only when there is one", async () => {
    const calls = stub();
    await lifecycleApi.records(1, { member: 9, active: true, page: 1, page_size: 25 });
    await lifecycleApi.createRecord(1, recordPayload(form({ proposeFine: true, fine: "150000.00" })));
    await lifecycleApi.createRecord(1, recordPayload(form({ files: [new File(["x"], "chek.jpg", { type: "image/jpeg" })] })));
    await lifecycleApi.withdrawRecord(1, 4, "Xato bilan yozilgan");
    await lifecycleApi.proposeFine(1, 4, "200000.00");
    await lifecycleApi.suspensions(1);
    await lifecycleApi.suspend(1, { member_id: 9, until: null, reason: "Kassa tekshirilmoqda" });
    await lifecycleApi.reinstate(1, 6);
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
      "GET lifecycle/discipline/?member=9&active=true&page=1&page_size=25",
      "POST lifecycle/discipline/",
      "POST lifecycle/discipline/",
      "POST lifecycle/discipline/4/withdraw/",
      "POST lifecycle/discipline/4/fine/",
      "GET lifecycle/suspensions/",
      "POST lifecycle/suspensions/",
      "POST lifecycle/suspensions/6/reinstate/",
    ]);
    expect(calls[1]!.body).toEqual({ member_id: 9, kind: "written_warning", category: "storage_breach", incident_on: "2026-11-01", description: "Insulin muzlatgichdan tashqarida qolgan.", fine_amount: "150000.00" });
    expect(calls[2]!.body).toEqual({ member_id: "9", kind: "written_warning", category: "storage_breach", incident_on: "2026-11-01", description: "Insulin muzlatgichdan tashqarida qolgan.", evidence: "file:chek.jpg" });
    expect(calls[4]!.body).toEqual({ amount: "200000.00" });
    expect(calls[6]!.body).toEqual({ member_id: 9, until: null, reason: "Kassa tekshirilmoqda" });
  });

  it("registers behind the hr switch with discipline first, the Record tab and the header actions", () => {
    expect(module).toMatchObject({ id: "lifecycle", group: "people", order: 50, feature: "hr" });
    expect(module.nav?.map((item) => item.key)).toEqual(["discipline", "suspensions", "org", "terminations", "changes", "equipment", "reviews"]);
    expect(module.personTabs?.map((tab) => tab.id)).toEqual(["record"]);
    expect(Object.keys(module.extensions ?? {})).toEqual(["people.profile.actions"]);
    expect(module.invalidates).toEqual(["lifecycle"]);
    expect(lifecycleKeys.records(1, { member: 9 })).toEqual([1, "lifecycle", "records", { member: 9 }]);
  });
});

describe("Person 360 header actions", () => {
  const person = (status = "approved", suspend = true) => ({ id: 9, name: "Alisher Valiyev", status, can: { suspend } });

  async function mountAs(perms: Perm[], p = person()) {
    const app = await testApp("/c/1/people/9");
    useSessionStore().me = me([company({ is_owner: false, role: { id: 3, name: "Manager" }, permissions: perms })]);
    const { wrapper } = mountWithProviders(ProfileActions, { plugins: app.plugins, props: { context: { companyId: 1, memberId: 9, person: p } } });
    await flushPromises();
    return wrapper;
  }

  it("offers a warning to hr.discipline and suspending to hr.suspend, nothing to readers", async () => {
    stub();
    expect((await mountAs(["hr.view"])).find("[data-lifecycle-actions]").exists()).toBe(false);
    const warn = await mountAs(["hr.discipline"]);
    expect(warn.text()).toBe(en["lifecycle.person.warn"]);
    const suspend = await mountAs(["hr.suspend"]);
    expect(suspend.text()).toBe(en["lifecycle.suspend.button"]);
    const both = await mountAs(["hr.discipline", "hr.suspend"]);
    expect(both.text()).toContain(en["lifecycle.person.discipline"]);
  });

  it("does not offer suspending someone already suspended or whom the server says may not be", async () => {
    stub();
    expect((await mountAs(["hr.suspend"], person("suspended"))).find("[data-lifecycle-actions]").exists()).toBe(false);
    expect((await mountAs(["hr.suspend"], person("approved", false))).find("[data-lifecycle-actions]").exists()).toBe(false);
  });

  it("leaves the person page its own Suspend where the company has HR switched off", async () => {
    mergeModuleMessages("people", { en: peopleEn, ru: peopleEn, uz: peopleEn });
    const PersonPage = (await import("@/modules/people/pages/PersonPage.vue")).default;
    const DropdownMenu = (await import("@/components/DropdownMenu.vue")).default;
    const detail = {
      id: 7,
      name: "Alisher Valiyev",
      status: "approved",
      suspended_until: null,
      fields: {},
      position: { id: 1, name: "Farmatsevt" },
      role: { id: 2, name: "Xodim" },
      home_branch: { id: 1, name: "Chilonzor" },
      branches: [{ id: 1, name: "Chilonzor" }],
      phone: "+998901234567",
      username: "",
      language: "uz",
      can: { suspend: true },
      overview: { trend: [], on_time: 0, late: 0, missed: 0, total: 0, on_time_percent: null, streak: 0, joined_on: "2025-10-06", days_off_this_year: 0, range: { from: "2026-10-04", to: "2026-11-02" }, upcoming_time_off: [] },
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string) => json(/\/people\/7\/(\?|$)/.test(input) ? detail : {})),
    );

    async function pageMenu(features: Company["features"]): Promise<{ labels: string[]; lifecycle: boolean }> {
      const app = await testApp("/c/1/people/7");
      useSessionStore().me = me([company({ features })]);
      const router = createRouter({
        history: createMemoryHistory(),
        routes: [
          { path: "/c/:companyId/people/:memberId(\\d+)/:tab?", component: PersonPage },
          { path: "/:any(.*)*", component: { render: () => null } },
        ],
      });
      await router.push("/c/1/people/7");
      const { wrapper } = mountWithProviders(PersonPage, { plugins: [app.pinia, router, i18n, [VueQueryPlugin, { queryClient: app.client }]] });
      await flushPromises();
      await flushPromises();
      expect(wrapper.text()).toContain("Alisher Valiyev");
      // The page's own "more" menu, not the lifecycle actions in the header (they have a Suspend of their own).
      const header = wrapper.findComponent(ProfileActions);
      const theirs = new Set(header.exists() ? header.findAllComponents(DropdownMenu).map((menu) => menu.vm.$.uid) : []);
      const labels = wrapper
        .findAllComponents(DropdownMenu)
        .filter((menu) => !theirs.has(menu.vm.$.uid))
        .flatMap((menu) => (menu.props() as { items: Array<{ label?: string }> }).items.map((item) => item.label ?? ""));
      return { labels, lifecycle: wrapper.find("[data-lifecycle-actions]").exists() };
    }

    // With HR on, suspending is the lifecycle's (the header actions); with HR off the people page keeps its own.
    const withHr = await pageMenu(["finance", "hr"]);
    expect(withHr.lifecycle).toBe(true);
    expect(withHr.labels).not.toContain(peopleEn["people.action.suspend"]);
    const withoutHr = await pageMenu(["finance"]);
    expect(withoutHr.lifecycle).toBe(false);
    expect(withoutHr.labels).toContain(peopleEn["people.action.suspend"]);
  });
});
