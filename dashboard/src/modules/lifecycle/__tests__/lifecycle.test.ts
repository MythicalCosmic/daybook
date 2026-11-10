// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Perm } from "@/core/perms";
import { mergeModuleMessages } from "@/i18n";
import { useSessionStore } from "@/stores/session";
import { company, json, me } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import { lifecycleApi, lifecycleKeys } from "../api";
import ChangeLines from "../components/ChangeLines.vue";
import ProfileActions from "../components/ProfileActions.vue";
import en from "../i18n/en.json";
import module from "../index";
import {
  changeAccess,
  changeFormErrors,
  changePayload,
  changeTab,
  daysLeft,
  handoverPercent,
  itemTitle,
  leavingAccess,
  lifecycleAccess,
  nextStep,
  NOTICE_DAYS,
  partSides,
  recordFormErrors,
  recordParams,
  recordPayload,
  recordState,
  shortNotice,
  startFormErrors,
  startPayload,
  suggestedChangeDay,
  suggestedLastDay,
  type ChangeForm,
  type RecordForm,
  type StartForm,
} from "../lib";
import type { ChangePart, JobSide } from "../types";

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
    expect(module.personTabs?.map((tab) => tab.id)).toEqual(["record", "career", "equipment"]);
    expect(Object.keys(module.extensions ?? {})).toEqual(["people.profile.actions", "people.offboard.step"]);
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
    expect(both.text()).toContain(en["lifecycle.person.actions"]);
  });

  it("offers changing the job to hr.manage and starting the leaving to hr.terminate", async () => {
    stub();
    expect((await mountAs(["hr.manage"])).text()).toBe(en["lifecycle.person.changeJob"]);
    expect((await mountAs(["hr.terminate"])).text()).toBe(en["lifecycle.person.startLeaving"]);
    expect((await mountAs(["hr.manage", "hr.terminate"])).text()).toContain(en["lifecycle.person.actions"]);
    // Someone who has left gets neither.
    expect((await mountAs(["hr.manage", "hr.terminate"], person("left"))).find("[data-lifecycle-actions]").exists()).toBe(false);
  });

  it("does not offer suspending someone already suspended or whom the server says may not be", async () => {
    stub();
    expect((await mountAs(["hr.suspend"], person("suspended"))).find("[data-lifecycle-actions]").exists()).toBe(false);
    expect((await mountAs(["hr.suspend"], person("approved", false))).find("[data-lifecycle-actions]").exists()).toBe(false);
  });
});

// ─── Leaving ───────────────────────────────────────────────────────────────

const startForm = (overrides: Partial<StartForm> = {}): StartForm => ({
  member: 9,
  kind: "contract_end",
  last_day: "2026-11-20",
  reason: "  Muddatli shartnoma tugaydi  ",
  final_payslip: true,
  leave_days: null,
  ...overrides,
});

describe("leaving", () => {
  it("reads who may see and run leavings", () => {
    const grant = (perms: string[]) => (perm: string) => perms.includes(perm);
    expect(leavingAccess(grant(["hr.view"]))).toEqual({ view: true, manage: false });
    expect(leavingAccess(grant(["hr.terminate"]))).toEqual({ view: true, manage: true });
    expect(leavingAccess(grant([]))).toEqual({ view: false, manage: false });
  });

  it("counts the days to the last day, and flags notice shorter than two weeks", () => {
    expect(daysLeft({ last_day: "2026-11-20", wished_last_day: "2026-11-25" }, "2026-11-10")).toBe(10);
    expect(daysLeft({ last_day: null, wished_last_day: "2026-11-12" }, "2026-11-10")).toBe(2);
    expect(daysLeft({ last_day: null, wished_last_day: null }, "2026-11-10")).toBeNull();
    expect(shortNotice(13)).toBe(true);
    expect(shortNotice(NOTICE_DAYS)).toBe(false);
    expect(shortNotice(null)).toBe(false);
    expect(suggestedLastDay("2026-11-10")).toBe("2026-11-24");
  });

  it("shows the handover's progress and names standard items by their kind", () => {
    expect(handoverPercent({ done: 2, total: 5 })).toBe(40);
    expect(handoverPercent({ done: 0, total: 0 })).toBe(0);
    expect(itemTitle({ title: "" })).toBeNull();
    expect(itemTitle({ title: " INV-0012 Kuryer skuteri " })).toBe("INV-0012 Kuryer skuteri");
  });

  it("checks and builds the start payload", () => {
    expect(startFormErrors(startForm(), "2026-11-10")).toEqual({});
    expect(startFormErrors(startForm({ member: null, last_day: null }), "2026-11-10")).toEqual({ member: "required", last_day: "required" });
    expect(startFormErrors(startForm({ last_day: "2026-11-09", leave_days: 400 }), "2026-11-10")).toEqual({ last_day: "past", leave_days: "range" });
    expect(startPayload(startForm())).toEqual({ member_id: 9, kind: "contract_end", last_day: "2026-11-20", final_payslip: true, reason: "Muddatli shartnoma tugaydi" });
    expect(startPayload(startForm({ reason: " ", leave_days: 6.5, final_payslip: false }))).toEqual({ member_id: 9, kind: "contract_end", last_day: "2026-11-20", final_payslip: false, leave_days: "6.5" });
  });
});

// ─── Job changes ───────────────────────────────────────────────────────────

const changeForm = (overrides: Partial<ChangeForm> = {}): ChangeForm => ({
  member: 9,
  effective_on: "2026-12-01",
  parts: ["position"],
  position: 4,
  branch: 2,
  department: null,
  pay_amount: null,
  pay_type: "monthly",
  reason: "  Provizor diplomi bor  ",
  approve: false,
  ...overrides,
});

const side = (overrides: Partial<JobSide> = {}): JobSide => ({ position: null, branch: null, branches: [], department: null, role: null, pay: null, ...overrides });

describe("job changes", () => {
  it("reads who may see and propose changes, and which tab a change sits in", () => {
    const grant = (perms: string[]) => (perm: string) => perms.includes(perm);
    expect(changeAccess(grant(["hr.view"]))).toEqual({ view: true, propose: false });
    expect(changeAccess(grant(["hr.manage"]))).toEqual({ view: true, propose: true });
    expect(changeTab({ status: "proposed" })).toBe("proposed");
    expect(changeTab({ status: "approved" })).toBe("upcoming");
    expect(changeTab({ status: "applied" })).toBe("applied");
    expect(changeTab({ status: "rejected" })).toBe("closed");
    expect(changeTab({ status: "cancelled" })).toBe("closed");
    expect(suggestedChangeDay("2026-11-10")).toBe("2026-12-01");
    expect(suggestedChangeDay("2026-12-31")).toBe("2027-01-01");
  });

  it("names what is missing: a person, a day from today, a part, its value, a reason", () => {
    expect(changeFormErrors(changeForm(), "2026-11-10")).toEqual({});
    expect(changeFormErrors(changeForm({ member: null, effective_on: "2026-11-09", parts: [], reason: " " }), "2026-11-10")).toEqual({
      member: "required",
      effective_on: "past",
      parts: "nothing",
      reason: "required",
    });
    expect(changeFormErrors(changeForm({ parts: ["position", "branch", "pay"], position: null, branch: null, pay_amount: "0.00" }), "2026-11-10")).toEqual({
      position: "required",
      branch: "required",
      pay_amount: "amount",
    });
  });

  it("sends only the parts that change, the department cleared as null, and approve when asked", () => {
    expect(changePayload(changeForm())).toEqual({ member_id: 9, effective_on: "2026-12-01", reason: "Provizor diplomi bor", position_id: 4 });
    expect(changePayload(changeForm({ parts: ["department", "pay"], pay_amount: "6500000.00", approve: true }))).toEqual({
      member_id: 9,
      effective_on: "2026-12-01",
      reason: "Provizor diplomi bor",
      department_id: null,
      pay_amount: "6500000.00",
      pay_type: "monthly",
      approve: true,
    });
    expect(changePayload(changeForm({ parts: ["branch"] }))).toEqual({ member_id: 9, effective_on: "2026-12-01", reason: "Provizor diplomi bor", branch_id: 2 });
  });

  it("reads before and after of a part by name", () => {
    const change = { before: side({ position: { id: 1, name: "Farmatsevt" } }), after: side({ position: { id: 4, name: "Provizor" } }) };
    expect(partSides(change, "position")).toEqual({ was: "Farmatsevt", now: "Provizor" });
    expect(partSides(change, "department")).toEqual({ was: null, now: null });
  });

  it("shows the pay only when the server sent it, a lock otherwise", async () => {
    const app = await testApp("/c/1/lifecycle/job-changes");
    const base = { parts: ["position", "pay"] as ChangePart[], has_pay: true, before: side({ position: { id: 1, name: "Farmatsevt" } }), after: side({ position: { id: 4, name: "Provizor" } }) };
    const hidden = mountWithProviders(ChangeLines, { plugins: app.plugins, props: { change: base } }).wrapper;
    expect(hidden.find('[data-part="position"]').text()).toContain("Farmatsevt");
    expect(hidden.find('[data-part="position"]').text()).toContain("Provizor");
    expect(hidden.find('[data-part="pay"]').text()).toContain(en["lifecycle.changes.payChanges"]);
    const shown = mountWithProviders(ChangeLines, {
      plugins: app.plugins,
      props: {
        change: {
          ...base,
          before: { ...base.before, pay: { amount: "5200000.00", currency: "UZS", pay_type: "monthly" } },
          after: { ...base.after, pay: { amount: "6500000.00", currency: "UZS", pay_type: "monthly" } },
        },
      },
    }).wrapper;
    expect(shown.find('[data-part="pay"]').text()).not.toContain(en["lifecycle.changes.payChanges"]);
    expect(shown.find('[data-part="pay"]').text()).toContain(en["lifecycle.payType.monthly"]);
  });
});

describe("leaving and job change api", () => {
  it("calls the endpoints with the bodies the server reads", async () => {
    const calls = stub();
    await lifecycleApi.leavings(1, { status: "agreed", page: 1 });
    await lifecycleApi.leavingCounts(1);
    await lifecycleApi.startLeaving(1, startPayload(startForm()));
    await lifecycleApi.agreeLeaving(1, 5, { last_day: "2026-11-20" });
    await lifecycleApi.declineLeaving(1, 5, "Gaplashdik, qoladi");
    await lifecycleApi.withdrawLeaving(1, 5, "Qolishga kelishdik");
    await lifecycleApi.updateLeaving(1, 5, { rehire: "yes" });
    await lifecycleApi.retryLeaving(1, 5);
    await lifecycleApi.addHandoverItem(1, 5, { title: "Seyf kaliti" });
    await lifecycleApi.setHandoverItem(1, 5, 31, { done: true });
    await lifecycleApi.removeHandoverItem(1, 5, 31);
    await lifecycleApi.changes(1, { status: "proposed" });
    await lifecycleApi.currentJob(1, 9);
    await lifecycleApi.proposeChange(1, changePayload(changeForm()));
    await lifecycleApi.approveChange(1, 7);
    await lifecycleApi.rejectChange(1, 7, "Hozircha emas");
    await lifecycleApi.cancelChange(1, 7);
    await lifecycleApi.retryChange(1, 7);
    await lifecycleApi.career(1, 9);
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
      "GET lifecycle/terminations/?status=agreed&page=1",
      "GET lifecycle/terminations/counts/",
      "POST lifecycle/terminations/",
      "POST lifecycle/terminations/5/agree/",
      "POST lifecycle/terminations/5/decline/",
      "POST lifecycle/terminations/5/withdraw/",
      "PATCH lifecycle/terminations/5/",
      "POST lifecycle/terminations/5/retry/",
      "POST lifecycle/terminations/5/handover/",
      "PATCH lifecycle/terminations/5/handover/31/",
      "DELETE lifecycle/terminations/5/handover/31/",
      "GET lifecycle/job-changes/?status=proposed",
      "GET lifecycle/job-changes/current/?member=9",
      "POST lifecycle/job-changes/",
      "POST lifecycle/job-changes/7/approve/",
      "POST lifecycle/job-changes/7/reject/",
      "POST lifecycle/job-changes/7/cancel/",
      "POST lifecycle/job-changes/7/retry/",
      "GET lifecycle/people/9/career/",
    ]);
    expect(calls[4]!.body).toEqual({ reason: "Gaplashdik, qoladi" });
    expect(calls[9]!.body).toEqual({ done: true });
    expect(calls[13]!.body).toEqual({ member_id: 9, effective_on: "2026-12-01", reason: "Provizor diplomi bor", position_id: 4 });
    expect(lifecycleKeys.leaving(1, 5)).toEqual([1, "lifecycle", "leaving", { id: 5 }]);
  });
});
