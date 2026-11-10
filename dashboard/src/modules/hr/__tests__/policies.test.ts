// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { confirmQueue, settleConfirm } from "@/components/useConfirm";
import { mergeModuleMessages } from "@/i18n";
import { company, json, me } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";
import { useSessionStore } from "@/stores/session";
import type { Perm } from "@/core/perms";

import en from "../i18n/en.json";
import module from "../index";
import PoliciesPage from "../pages/PoliciesPage.vue";
import PolicyPage from "../pages/PolicyPage.vue";
import { policyApi } from "../policies/api";
import { audienceParts, daysUntil, diffCounts, diffText, paragraphs, policyView, signedPercent, wordDiff } from "../policies/lib";
import PersonPolicies from "../policies/PersonPolicies.vue";
import PolicyCard from "../policies/PolicyCard.vue";
import PublishDialog from "../policies/PublishDialog.vue";
import type { Policy, PolicyDetail } from "../policies/types";

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

function policy(overrides: Partial<PolicyDetail> = {}): PolicyDetail {
  return {
    id: 4,
    title: "Dori berish qoidalari",
    category: "dispensing",
    requires_ack: true,
    ack_within_days: 7,
    is_active: true,
    positions: [
      { id: 2, name: "Farmatsevt" },
      { id: 3, name: "Provizor" },
    ],
    branches: [],
    version: { id: 11, number: 2, published_at: "2026-10-31T04:30:00Z", asks_again: true },
    ack_number: 2,
    draft: null,
    tally: { total: 11, signed: 8, waiting: 1, late: 2 },
    due_on: "2026-11-07",
    can_change: true,
    created_at: "2026-07-12T10:00:00Z",
    updated_at: "2026-10-31T04:30:00Z",
    versions: [
      { id: 11, number: 2, change_note: "Elektron retseptlar bo‘limi qo‘shildi", asks_again: true, published_at: "2026-10-31T04:30:00Z", published_by: "Dilnoza Karimova", is_draft: false, has_file: true, file_type: "pdf", created_at: "2026-10-30T11:40:00Z", updated_at: "2026-10-31T04:30:00Z" },
      { id: 7, number: 1, change_note: "", asks_again: true, published_at: "2026-07-12T05:00:00Z", published_by: "Dilnoza Karimova", is_draft: false, has_file: false, file_type: null, created_at: "2026-07-11T10:20:00Z", updated_at: "2026-07-12T05:00:00Z" },
    ],
    audience_count: 11,
    created_by: "Dilnoza Karimova",
    ...overrides,
  };
}

const page = <T>(results: T[]) => ({ count: results.length, next: null, previous: null, results });

describe("api", () => {
  it("calls the policy endpoints, sending a draft's file as a form only when there is one", async () => {
    const calls = stub();
    await policyApi.list(1, { view: "all", category: ["storage"], q: "harorat" });
    await policyApi.get(1, 4);
    await policyApi.create(1, { title: "Kassa intizomi", category: "conduct", position_ids: [2], branch_ids: [], requires_ack: true, ack_within_days: 7, body: "<p>Chek</p>" });
    await policyApi.update(1, 4, { is_active: false });
    await policyApi.saveDraft(1, 4, { body: "<p>Yangi</p>", change_note: "Tuzatish" });
    await policyApi.saveDraft(1, 4, { file: new File(["%PDF"], "buyruq.pdf", { type: "application/pdf" }) });
    await policyApi.discardDraft(1, 4);
    await policyApi.publish(1, 4, { asks_again: false, change_note: "Imlo" });
    await policyApi.version(1, 4, 2);
    await policyApi.signatures(1, 4, { state: "late", page: 1, page_size: 25 });
    await policyApi.remind(1, 4, [9]);
    await policyApi.remind(1, 4);
    await policyApi.audience(1, { position: [2, 3], branch: [1] });
    await policyApi.person(1, 9);
    await policyApi.remove(1, 5);
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
      "GET hr/policies/?view=all&category=storage&q=harorat",
      "GET hr/policies/4/",
      "POST hr/policies/",
      "PATCH hr/policies/4/",
      "PUT hr/policies/4/draft/",
      "PUT hr/policies/4/draft/",
      "DELETE hr/policies/4/draft/",
      "POST hr/policies/4/publish/",
      "GET hr/policies/4/versions/2/",
      "GET hr/policies/4/acknowledgements/?state=late&page=1&page_size=25",
      "POST hr/policies/4/remind/",
      "POST hr/policies/4/remind/",
      "GET hr/policies/audience/?position=2&position=3&branch=1",
      "GET hr/people/9/policies/",
      "DELETE hr/policies/5/",
    ]);
    expect(calls[4]!.body).toEqual({ body: "<p>Yangi</p>", change_note: "Tuzatish" });
    expect(calls[5]!.body).toEqual({ file: "file:buyruq.pdf" });
    expect(calls[7]!.body).toEqual({ asks_again: false, change_note: "Imlo" });
    expect(calls[10]!.body).toEqual({ member_ids: [9] });
    expect(calls[11]!.body).toEqual({});
  });

  it("registers the real pages instead of the coming-soon one, with the late badge and the palette command", async () => {
    const names = module.routes.map((route) => route.name);
    expect(names).toEqual(expect.arrayContaining(["hr.policies", "hr.policy.new", "hr.policy", "hr.policy.edit"]));
    const list = module.routes.find((route) => route.name === "hr.policies")!;
    expect(list.props).toBeUndefined();
    const loaded = (await (list.component as () => Promise<{ default: unknown }>)()).default;
    expect(loaded).toBe(PoliciesPage);
    const nav = module.nav!.find((item) => item.key === "policies")!;
    expect(nav.badge?.({ counters: { "hr.policies": 3 }, versions: {} })).toBe(3);
    expect(module.deepLinks?.policy?.("12")).toBe("hr/policies/12");
    expect(Object.keys(en).some((key) => key.startsWith("hr.soon.policies."))).toBe(false);
  });
});

describe("comparing versions", () => {
  it("splits a text into tidy paragraphs", () => {
    expect(paragraphs("  1. Umumiy\n\n Dorilar   faqat  \r\nretsept bilan ")).toEqual(["1. Umumiy", "Dorilar faqat", "retsept bilan"]);
  });

  it("marks the words changed inside a paragraph", () => {
    expect(wordDiff("Retseptli dorilar faqat retsept bilan beriladi.", "Retseptli dorilar faqat elektron retsept bilan beriladi.")).toEqual([
      { kind: "same", text: "Retseptli dorilar faqat " },
      { kind: "added", text: "elektron " },
      { kind: "same", text: "retsept bilan beriladi." },
    ]);
  });

  it("tells added, removed and changed paragraphs apart", () => {
    const before = "1. Kim dori beradi\nFaqat farmatsevt beradi.\nKassada chek beriladi.\nEski band.";
    const after = "1. Kim dori beradi\nFaqat farmatsevt yoki provizor beradi.\nKassada chek beriladi.\n4. Elektron retseptlar";
    const blocks = diffText(before, after);
    expect(blocks.map((block) => block.kind)).toEqual(["same", "changed", "same", "removed", "added"]);
    expect(diffCounts(blocks)).toEqual({ added: 1, removed: 1, changed: 1 });
    expect(blocks[1]!.parts.filter((part) => part.kind === "added").map((part) => part.text.trim())).toEqual(["yoki provizor"]);
    expect(diffText("Bir xil.", "Bir xil.")).toEqual([{ kind: "same", parts: [{ kind: "same", text: "Bir xil." }] }]);
  });
});

describe("helpers", () => {
  it("says who a policy applies to, where it is listed and how far the signing got", () => {
    const words = { everyPosition: "Every position", everyBranch: "Every branch" };
    expect(audienceParts(policy(), words)).toEqual({ positions: "Farmatsevt, Provizor", branches: "Every branch" });
    expect(policyView(policy())).toBe("active");
    expect(policyView(policy({ version: null }))).toBe("drafts");
    expect(policyView(policy({ is_active: false }))).toBe("archived");
    expect(signedPercent({ total: 11, signed: 8, waiting: 1, late: 2 })).toBe(73);
    expect(signedPercent({ total: 0, signed: 0, waiting: 0, late: 0 })).toBe(100);
    expect(daysUntil("2026-11-07", "2026-11-05")).toBe(2);
    expect(daysUntil("2026-11-03", "2026-11-05")).toBe(-2);
  });
});

describe("pages", () => {
  async function asManager(perms: Perm[] = ["hr.view", "hr.manage"], path = "/c/1/hr/policies") {
    const app = await testApp(path);
    useSessionStore().me = me([company({ is_owner: false, role: { id: 3, name: "HR" }, permissions: perms })]);
    return app;
  }

  it("lists the policies in force with their signing, and the drafts and archive under their tabs", async () => {
    vi.useFakeTimers({ now: new Date("2026-11-05T06:00:00Z"), toFake: ["Date"] });
    try {
      const draft: Policy = { ...policy({ id: 5, title: "Sanitariya kuni", category: "safety", version: null, tally: null, due_on: null }) };
      stub({ "hr/policies/": [policy(), draft] });
      const app = await asManager();
      const { wrapper } = mountWithProviders(PoliciesPage, { plugins: app.plugins });
      await flushPromises();
      await flushPromises();
      const cards = wrapper.findAll("[data-policy]");
      expect(cards).toHaveLength(1);
      const text = cards[0]!.text();
      expect(text).toContain("Dori berish qoidalari");
      expect(text).toContain("8 of 11 signed");
      expect(text).toContain("2 late");
      expect(text).toContain("Farmatsevt, Provizor");
      expect(wrapper.text()).toContain(en["hr.policy.new"]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows a policy's numbers and its people, and reminds everyone still to sign", async () => {
    const calls = stub({
      "hr/policies/4/acknowledgements/": page([
        { member: { id: 9, name: "Alisher Valiyev", photo_url: null }, position: { id: 2, name: "Farmatsevt" }, branch: { id: 1, name: "Chilonzor", code: "CHL" }, state: "signed", asked_at: "2026-10-31T04:30:00Z", due_on: "2026-11-07", signed_at: "2026-11-01T05:10:00Z", signed_number: 2, reminded_at: null, earlier_signed_at: null },
        { member: { id: 10, name: "Nigora Azimova", photo_url: null }, position: { id: 2, name: "Farmatsevt" }, branch: { id: 2, name: "Yunusobod", code: "YNS" }, state: "late", asked_at: "2026-10-31T04:30:00Z", due_on: "2026-11-03", signed_at: null, signed_number: null, reminded_at: "2026-11-02T03:30:00Z", earlier_signed_at: "2026-07-14T16:00:00Z" },
      ]),
      "hr/policies/4/remind/": { reminded: 3 },
      "hr/policies/4/": policy(),
    });
    const app = await asManager(["hr.view", "hr.manage"], "/c/1/hr/policies/4");
    await app.router.addRoute({ path: "/c/:cid/hr/policies/:policyId", component: { render: () => null } });
    await app.router.replace("/c/1/hr/policies/4");
    const { wrapper } = mountWithProviders(PolicyPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    expect(wrapper.find("[data-policy-header]").text()).toContain("Dori berish qoidalari");
    expect(wrapper.text()).toContain("Alisher Valiyev");
    expect(wrapper.text()).toContain("Nigora Azimova");
    expect(wrapper.text()).toContain(en["hr.policy.signedBefore"]);

    await wrapper.find("[data-remind-all]").trigger("click");
    await flushPromises();
    // The confirm says how many; confirming (as ConfirmDialog does) sends the reminders.
    const [asked] = confirmQueue.value;
    expect(asked!.request.title).toBe("Remind 3 people?");
    await asked!.request.onConfirm?.("");
    settleConfirm(asked!.id, { reason: "" }, 0);
    await flushPromises();
    expect(calls.filter((call) => call.url === "hr/policies/4/remind/" && call.method === "POST").map((call) => call.body)).toEqual([{}]);
    confirmQueue.value = [];
  });

  it("asks before publishing whether everyone signs again or the signatures stay", async () => {
    const app = await asManager();
    const confirmed: Array<{ asks_again: boolean; change_note: string }> = [];
    const { wrapper } = mountWithProviders(PublishDialog, {
      plugins: app.plugins,
      props: { open: true, number: 3, republish: true, requiresAck: true, days: 7, audience: 11, changeNote: "Imlo", onConfirm: (input: { asks_again: boolean; change_note: string }) => confirmed.push(input) },
    });
    await flushPromises();
    expect(document.body.textContent).toContain("11 people will be asked to read and sign it within 7 days.");
    const keep = [...document.body.querySelectorAll("[role='radio'], input[type='radio']")].find((element) => element.closest("label, [role='radio']")?.textContent?.includes(en["hr.policy.asks.keep"]));
    (keep as HTMLElement | undefined)?.click();
    await flushPromises();
    (document.body.querySelector("[data-publish-confirm]") as HTMLButtonElement).click();
    await flushPromises();
    expect(confirmed).toEqual([{ asks_again: false, change_note: "Imlo" }]);
    wrapper.unmount();
  });

  it("says on a person's HR tab where they stand on each policy", async () => {
    vi.useFakeTimers({ now: new Date("2026-11-05T06:00:00Z"), toFake: ["Date"] });
    try {
      stub({
        "hr/people/9/policies/": {
          current: [
            { policy: { id: 4, title: "Dori berish qoidalari", category: "dispensing" }, number: 2, state: "late", due_on: "2026-11-03", signed_at: null, signed_number: null },
            { policy: { id: 6, title: "Kassa intizomi", category: "conduct" }, number: 2, state: "signed", due_on: "2026-11-06", signed_at: "2026-10-31T09:00:00Z", signed_number: 2 },
          ],
          history: [
            { policy: { id: 6, title: "Kassa intizomi", category: "conduct" }, number: 2, signed_number: 2, signed_at: "2026-10-31T09:00:00Z" },
            { policy: { id: 4, title: "Dori berish qoidalari", category: "dispensing" }, number: 1, signed_number: 1, signed_at: "2026-07-13T09:00:00Z" },
          ],
        },
      });
      const app = await asManager(["hr.view"]);
      const { wrapper } = mountWithProviders(PersonPolicies, { plugins: app.plugins, props: { memberId: 9 } });
      await flushPromises();
      await flushPromises();
      const text = wrapper.find("[data-hr-policies]").text();
      expect(text).toContain("Dori berish qoidalari");
      expect(text).toContain(en["hr.policy.state.late"]);
      expect(text).toContain("Earlier signatures: 1");
    } finally {
      vi.useRealTimers();
    }
  });

  it("draws a card's progress only for policies that ask for signatures", async () => {
    const app = await testApp("/c/1/hr/policies");
    const toRead = mountWithProviders(PolicyCard, { plugins: app.plugins, props: { policy: policy({ requires_ack: false, tally: null }), to: "/c/1/hr/policies/4" } });
    expect(toRead.wrapper.text()).toContain(en["hr.policy.toRead"]);
    expect(toRead.wrapper.find("[role='progressbar']").exists()).toBe(false);
    const asking = mountWithProviders(PolicyCard, { plugins: app.plugins, props: { policy: policy(), to: "/c/1/hr/policies/4" } });
    expect(asking.wrapper.find("[role='progressbar']").exists()).toBe(true);
  });
});
