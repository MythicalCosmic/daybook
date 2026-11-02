// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mergeModuleMessages } from "@/i18n";
import { company, json, me } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";
import { useSessionStore } from "@/stores/session";
import type { Perm } from "@/core/perms";

import { hrApi, hrKeys } from "../api";
import DaysChip from "../components/DaysChip.vue";
import PersonHrTab from "../components/PersonHrTab.vue";
import en from "../i18n/en.json";
import module from "../index";
import type { HrProfile } from "../types";

interface Call {
  method: string;
  url: string;
  body: unknown;
}

/** fetch answers by URL prefix (relative to the company), recording every call. */
function stub(routes: Record<string, unknown> = {}): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const raw = init?.body;
      const body = raw instanceof FormData ? Object.fromEntries([...raw.entries()].map(([k, v]) => [k, typeof v === "string" ? v : `file:${(v as File).name}`])) : raw ? JSON.parse(String(raw)) : undefined;
      const url = input.replace("/api/v1/owner/companies/1/", "");
      calls.push({ method: init?.method ?? "GET", url, body });
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

describe("api", () => {
  it("calls the HR endpoints, sending files as forms only when there is one", async () => {
    const calls = stub();
    await hrApi.overview(1);
    await hrApi.profile(1, 9);
    await hrApi.updateProfile(1, 9, { city: "Toshkent", pinfl: "31204567890045" });
    await hrApi.sensitive(1, 9);
    await hrApi.addContact(1, 9, { name: "Gulnora", relation: "Onasi", phone: "+998901234567" });
    await hrApi.documents(1, { expiring_within: 30, kind: ["medical_book"], page: 1, page_size: 25 });
    await hrApi.uploadDocument(1, { member_id: 9, kind: "medical_book", title: "", number: "", issued_on: null, expires_on: "2027-05-01", visible_to_employee: true, file: new File(["%PDF"], "book.pdf", { type: "application/pdf" }) });
    await hrApi.updateDocument(1, 5, { expires_on: "2027-06-01" });
    await hrApi.verifyDocument(1, 5);
    await hrApi.compliance(1, {});
    await hrApi.contracts(1, { status: ["active"], ending_within: 30 });
    await hrApi.contractAction(1, 3, "renew", { ends_on: "2027-11-30" });
    await hrApi.contractAction(1, 3, "pass-probation");
    await hrApi.previewTemplate(1, 2, { member_id: 9, body: "<p>{{employee_full_name}}</p>" });
    await hrApi.celebrations(1, { from: "2026-11-01", to: "2026-11-30" });
    await hrApi.saveSettings(1, { document_warn_days: 45 });
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
      "GET hr/overview/",
      "GET hr/people/9/profile/",
      "PATCH hr/people/9/profile/",
      "GET hr/people/9/sensitive/",
      "POST hr/people/9/emergency-contacts/",
      "GET hr/documents/?expiring_within=30&kind=medical_book&page=1&page_size=25",
      "POST hr/documents/",
      "PATCH hr/documents/5/",
      "POST hr/documents/5/verify/",
      "GET hr/documents/compliance/",
      "GET hr/contracts/?status=active&ending_within=30",
      "POST hr/contracts/3/renew/",
      "POST hr/contracts/3/pass-probation/",
      "POST hr/contract-templates/2/preview/",
      "GET hr/celebrations/?from=2026-11-01&to=2026-11-30",
      "PATCH hr/settings/",
    ]);
    expect(calls[6]!.body).toEqual({ member_id: "9", kind: "medical_book", title: "", number: "", expires_on: "2027-05-01", visible_to_employee: "true", file: "file:book.pdf" });
    expect(calls[7]!.body).toEqual({ expires_on: "2027-06-01" });
    expect(calls[11]!.body).toEqual({ ends_on: "2027-11-30" });
  });

  it("registers behind the hr switch, with the overview first, a Person 360 tab and a settings panel", () => {
    expect(module).toMatchObject({ id: "hr", group: "people", order: 40, feature: "hr", perm: ["hr.view", "hr.hiring"] });
    expect(module.nav?.map((item) => item.to)).toEqual(["hr", "hr/documents", "hr/contracts", "hr/contract-templates", "hr/celebrations", "hr/policies", "hr/hiring"]);
    expect(module.routes.every((route) => typeof route.component === "function")).toBe(true);
    expect(module.personTabs?.map((tab) => [tab.id, tab.perm])).toEqual([["hr", "hr.view"]]);
    expect(module.settings?.map((panel) => [panel.id, panel.perm])).toEqual([["hr", "hr.manage"]]);
    expect(module.invalidates).toEqual(["hr"]);
    expect(module.deepLinks?.contract?.("12")).toBe("hr/contracts?contract=12");
    expect(hrKeys.documents(1, { kind: ["passport"] })).toEqual([1, "hr", "documents", { kind: ["passport"] }]);
  });
});

describe("DaysChip", () => {
  it("says how far a date is, and nothing while it is far", async () => {
    vi.useFakeTimers({ now: new Date("2026-11-02T06:00:00Z"), toFake: ["Date"] });
    try {
      const app = await testApp("/c/1/hr");
      const at = (props: Record<string, unknown>) => mountWithProviders(DaysChip, { plugins: app.plugins, props }).wrapper.text();
      expect(at({ day: "2026-11-07", prefix: "expires" })).toBe("Expires in 5 days");
      expect(at({ day: "2026-11-03", prefix: "ends" })).toBe("Ends in 1 day");
      expect(at({ day: "2026-11-02", prefix: "probation" })).toBe("Probation ends today");
      expect(at({ day: "2026-10-30", prefix: "expires" })).toBe("Expired 3 days ago");
      expect(at({ day: "2027-03-01", prefix: "expires" })).toBe("");
      expect(at({ day: "2027-03-01", prefix: "expires", always: true })).toBe("Expires in 119 days");
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("Person 360 › HR", () => {
  /** The profile as the server shapes it for a viewer holding `perms`. */
  const profileFor = (perms: Perm[]): HrProfile => ({
    member: { id: 9, name: "Alisher Valiyev" },
    first_name: "Alisher",
    last_name: "Valiyev",
    status: "approved",
    position: { id: 7, name: "Farmatsevt" },
    department: null,
    manager: null,
    home_branch: { id: 1, name: "Chilonzor", code: "CHL" },
    employee_number: "CHL-014",
    middle_name: "Rustamovich",
    birth_date: "1996-03-14",
    show_birthday: true,
    gender: "male",
    hire_date: "2024-02-01",
    employment_type: "full_time",
    personal_phone: "+998901112233",
    email: "",
    address: "Bunyodkor 12",
    city: "Toshkent",
    pinfl: "••••••••••0045",
    passport: "AA•••••67",
    passport_shared: false,
    tin: "301234567",
    payout_method: "card",
    payout_card: "••••••••••••9012",
    terminated_on: null,
    termination_reason: "",
    termination_note: "",
    notes: perms.includes("hr.manage") ? "Kechki smenaga o‘tishni so‘ragan." : null,
    emergency_contacts: [{ id: 1, name: "Gulnora Valiyeva", relation: "Onasi", phone: "+998907776655" }],
    can_edit: perms.includes("hr.manage"),
    can_reveal: perms.includes("hr.sensitive"),
  });
  const routes = (perms: Perm[]) => ({
    "hr/people/9/profile/": profileFor(perms),
    "hr/people/9/sensitive/": { member: { id: 9, name: "Alisher Valiyev", photo_url: null }, pinfl: "31204567890045", passport: "AA1234567", payout_card: "8600123456789012", tin: "301234567" },
    "hr/documents/": { count: 0, next: null, previous: null, results: [] },
    "hr/contracts/": { count: 0, next: null, previous: null, results: [] },
    "hr/settings/": { document_warn_days: 30, contract_warn_days: 30, probation_warn_days: 7, celebrations_enabled: true, celebrate_anniversaries: true },
  });

  async function mountAs(perms: Perm[]) {
    const app = await testApp("/c/1/people/9/hr");
    useSessionStore().me = me([company({ is_owner: false, role: { id: 3, name: "Manager" }, permissions: perms })]);
    const { wrapper } = mountWithProviders(PersonHrTab, { plugins: app.plugins, props: { memberId: 9 } });
    await flushPromises();
    await flushPromises();
    return wrapper;
  }

  it("shows the IDs masked and reveals them through the audited read for hr.sensitive", async () => {
    const perms: Perm[] = ["hr.view", "hr.manage", "hr.sensitive"];
    const calls = stub(routes(perms));
    const wrapper = await mountAs(perms);
    expect(wrapper.find("[data-id-field='passport']").text()).toContain("AA•••••67");
    expect(wrapper.find("[data-id-field='pinfl']").text()).toContain("••••••••••0045");
    expect(calls.some((c) => c.url.includes("sensitive"))).toBe(false);
    // HR's note, which the server sends to hr.manage only.
    expect(wrapper.find("[data-hr-notes]").text()).toContain("Kechki smenaga");

    await wrapper.find("[data-reveal]").trigger("click");
    await flushPromises();
    expect(calls.filter((c) => c.url === "hr/people/9/sensitive/")).toHaveLength(1);
    expect(wrapper.find("[data-id-field='passport']").text()).toContain("AA1234567");
    expect(wrapper.find("[data-id-field='pinfl']").text()).toContain("3120 4567 8900 45");
    expect(wrapper.find("[data-hr-ids]").text()).toContain(en["hr.profile.revealAudited"]);
    // The emergency contact and the edit button are there for hr.manage.
    expect(wrapper.find("[data-hr-contacts]").text()).toContain("Gulnora Valiyeva");
    expect(wrapper.find("[data-hr-profile] button").exists()).toBe(true);
    expect(wrapper.find("[data-hr-contacts] button").exists()).toBe(true);
  });

  it("reads only, with no reveal and no edit, for hr.view", async () => {
    stub(routes(["hr.view"]));
    const wrapper = await mountAs(["hr.view"]);
    expect(wrapper.find("[data-reveal]").exists()).toBe(false);
    expect(wrapper.find("[data-hr-notes]").exists()).toBe(false);
    expect(wrapper.find("[data-hr-ids]").text()).toContain(en["hr.profile.maskedHint"]);
    expect(wrapper.find("[data-hr-profile] button").exists()).toBe(false);
    expect(wrapper.find("[data-hr-documents] button").exists()).toBe(false);
    expect(wrapper.find("[data-hr-contacts]").findAll("button")).toHaveLength(0);
  });
});
