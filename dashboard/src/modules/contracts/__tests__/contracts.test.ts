// The contracts screens against a stubbed API: the list (what needs a look first, the chips,
// the days left), a contract's page (the renewal decision, files, payments; no changes for
// someone who only reads money), what the form sends for a new lease with its rent in the
// forecast, the settings, and the date helpers.
// The registry first, as in the app (core/modules loads every module's index.ts).
import "@/core/modules";

import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter, type RouteRecordRaw } from "vue-router";

import type { Perm } from "@/core/perms";
import { i18n, mergeModuleMessages, setLanguage } from "@/i18n";
import { useCompanyStore } from "@/stores/company";
import { useSessionStore } from "@/stores/session";
import { company, json, me } from "@/test/fixtures";
import { mountWithProviders as mountRaw } from "@/test/plugins";

import ContractFormDialog from "../components/ContractFormDialog.vue";
import SettingsPanel from "../components/SettingsPanel.vue";
import en from "../i18n/en.json";
import ru from "../i18n/ru.json";
import uz from "../i18n/uz.json";
import { addDays, byAttention, dayTone, daysUntil, noticeDeadline, termPosition, termProgress } from "../lib";
import ContractPage from "../pages/ContractPage.vue";
import ContractsPage from "../pages/ContractsPage.vue";
import { routes } from "../routes";
import type { ContractDetail, ContractRow, Options, Summary } from "../types";

vi.setConfig({ testTimeout: 20_000 });

const mounted: Array<{ unmount: () => void }> = [];
const mountWithProviders: typeof mountRaw = (component, options) => {
  const result = mountRaw(component, options);
  mounted.push(result.wrapper);
  return result;
};

interface Call {
  method: string;
  path: string;
  body: unknown;
}

class NoResize {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

function stub(routesByCall: Record<string, (call: Call) => Response>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal("ResizeObserver", NoResize);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const path = url.replace(/^.*\/api\/v1\/owner\/companies\/1\//, "").split("?")[0]!;
      const body = init?.body && typeof init.body === "string" ? JSON.parse(init.body) : undefined;
      const call = { method: init?.method ?? "GET", path, body };
      calls.push(call);
      return routesByCall[`${call.method} ${path}`]?.(call) ?? json({ detail: "Not found." }, 404);
    }),
  );
  return calls;
}

async function settle(): Promise<void> {
  for (let i = 0; i < 8; i += 1) await flushPromises();
}

beforeEach(() => {
  mergeModuleMessages("contracts", { en, ru: en, uz: en });
  localStorage.clear();
});

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  document.body.innerHTML = "";
});

const TODAY = "2026-11-12";

const row = (overrides: Partial<ContractRow> = {}): ContractRow => ({
  id: 7,
  kind: "lease",
  title: "Chilonzor dorixonasi ijarasi",
  number: "IJ-2024/07",
  branch: { id: 1, name: "Chilonzor" },
  counterparty: { id: 3, name: "Rustam Qodirov (ijara)" },
  responsible: null,
  status: "active",
  starts_on: "2025-01-22",
  term_starts_on: "2026-01-22",
  ends_on: "2027-01-21",
  auto_renews: true,
  notice_deadline: "2026-11-22",
  key_day: "2026-11-22",
  days_left: 10,
  attention: "notice",
  amount: "9000000.00",
  period: "monthly",
  currency: "UZS",
  per_month: "9000000.00",
  in_forecast: true,
  has_rule: true,
  files: 2,
  ...overrides,
});

const detail = (overrides: Partial<ContractDetail> = {}): ContractDetail => ({
  ...row(),
  signed_on: "2025-01-10",
  renewal_months: 12,
  notice_days: 60,
  payment_day: 3,
  notes: "Bino 86 kv.m",
  terminated_on: null,
  termination_reason: "",
  last_renewed_on: "2026-01-22",
  renewal_confirmed: false,
  file_list: [
    { id: 1, kind: "signed", label: "", size: 2048, is_pdf: true, url: "/api/v1/files/abc/", uploaded_by: "Dilnoza Karimova", created_at: "2026-11-12T04:00:00Z" },
    { id: 2, kind: "annex", label: "Ijara haqi oshirilishi", size: 1024, is_pdf: true, url: "/api/v1/files/def/", uploaded_by: null, created_at: "2026-11-12T04:00:00Z" },
  ],
  dates: [
    { key: "signed", day: "2025-01-10", past: true },
    { key: "starts", day: "2025-01-22", past: true },
    { key: "renewed", day: "2026-01-22", past: true },
    { key: "notice", day: "2026-11-22", past: false },
    { key: "renews", day: "2027-01-21", past: false },
  ],
  rule: { id: 4, name: "Ijara: Chilonzor", is_active: true, category: { id: 9, name: "Ijara" }, account: { id: 2, name: "Asosiy bank hisobi" }, amount: "9000000.00", currency: "UZS", frequency: "monthly", day: 3, next_due_on: "2026-12-03", ends_on: null },
  payments: {
    items: [{ id: 50, occurred_on: "2026-11-03", amount: "9000000.00", currency: "UZS", base_amount: "9000000.00", description: "Chilonzor dorixonasi ijarasi, 11.2026", account: "Asosiy bank hisobi", by_rule: false }],
    count: 1,
    total: "9000000.00",
    this_year: "9000000.00",
    currency: "UZS",
    last_paid_on: "2026-11-03",
    next: { due_on: "2026-12-03", amount: "9000000.00", currency: "UZS" },
  },
  created_at: "2026-11-12T04:00:00Z",
  can: { manage: true },
  ...overrides,
});

const summary: Summary = {
  today: TODAY,
  counts: { draft: 0, active: 3, ending: 0, ended: 0, terminated: 0 },
  total: 3,
  in_force: 3,
  ending_soon: 1,
  notice_due: 1,
  monthly_cost: "29385000.00",
  currency: "UZS",
  unpriced: 0,
  remind_days: 30,
  notice_remind_days: 14,
};

const options: Options = {
  finance: true,
  base_currency: "UZS",
  categories: [{ id: 9, name: "Ijara", system_code: "rent" }],
  accounts: [
    { id: 2, name: "Asosiy bank hisobi", currency: "UZS" },
    { id: 5, name: "Dollar seyf", currency: "USD" },
  ],
  rules: [{ id: 4, name: "Ijara: Chilonzor", amount: "9000000.00", currency: "UZS", frequency: "monthly", counterparty: 3, branch: 1 }],
  parties: [{ id: 3, name: "Rustam Qodirov (ijara)", kind: "other" }],
};

async function pageApp(path: string, permissions?: Perm[]) {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-11-12T07:00:00Z"));
  const pinia = createPinia();
  setActivePinia(pinia);
  useSessionStore().me = me([permissions ? company({ is_owner: false, permissions, features: ["finance"] }) : company({ features: ["finance"] })]);
  useCompanyStore().setCurrent(1);
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/c/:companyId", children: routes.map((route) => ({ ...route, component: { render: () => null } }) as RouteRecordRaw) },
      { path: "/:any(.*)*", component: { render: () => null } },
    ],
  });
  await router.push(path);
  setLanguage("en");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return { pinia, router, plugins: [pinia, router, i18n, [VueQueryPlugin, { queryClient: client }]] as never };
}

describe("lib", () => {
  it("counts days and places dates on the term", () => {
    expect(daysUntil("2026-11-22", TODAY)).toBe(10);
    expect(daysUntil("2026-11-01", TODAY)).toBe(-11);
    expect(addDays("2026-12-31", -30)).toBe("2026-12-01");
    expect(noticeDeadline("2026-12-31", 30, true)).toBe("2026-12-01");
    expect(noticeDeadline("2026-12-31", 30, false)).toBeNull();
    expect(termProgress("2026-01-01", "2026-12-31", "2026-07-02")).toBeCloseTo(50, 0);
    expect(termProgress("2026-01-01", "2026-12-31", "2027-02-01")).toBe(100);
    expect(termProgress(null, "2026-12-31", TODAY)).toBeNull();
    expect(termPosition("2026-01-01", "2026-12-31", "2027-03-01")).toBeNull();
  });

  it("puts what needs a look first and colours the days left", () => {
    const sorted = byAttention([row({ id: 1, attention: null, key_day: "2026-11-20" }), row({ id: 2, attention: "ending", key_day: "2026-12-27" })]);
    expect(sorted.map((item) => item.id)).toEqual([2, 1]);
    expect(dayTone(row({ attention: "ending", days_left: 45 }))).toBe("warning");
    expect(dayTone(row({ attention: "ending", days_left: 5 }))).toBe("danger");
    expect(dayTone(row({ attention: null, days_left: 200 }))).toBe("neutral");
  });

  it("has the same keys in every language", () => {
    expect(Object.keys(uz).sort()).toEqual(Object.keys(en).sort());
    expect(Object.keys(ru).sort()).toEqual(Object.keys(en).sort());
  });
});

describe("the list", () => {
  it("shows what needs a look first, with the days left and the money", async () => {
    stub({
      "GET contracts/": () =>
        json([
          row(),
          row({ id: 8, title: "Yunusobod dorixonasi ijarasi", auto_renews: false, notice_deadline: null, key_day: "2026-12-27", ends_on: "2026-12-27", days_left: 45, attention: null, amount: "1400.00", currency: "USD", branch: { id: 2, name: "Yunusobod" } }),
          row({ id: 9, kind: "supply", title: "Dori vositalarini yetkazib berish", attention: null, amount: null, period: "once", key_day: "2026-12-15", days_left: 33, branch: null }),
        ]),
      "GET contracts/summary/": () => json(summary),
    });
    const app = await pageApp("/c/1/contracts");
    const { wrapper } = mountWithProviders(ContractsPage, { plugins: app.plugins });
    await settle();
    const attention = wrapper.find("[data-testid=contracts-attention]");
    expect(attention.text()).toContain("Chilonzor dorixonasi ijarasi");
    expect(attention.text()).toContain("Notice by");
    const rest = wrapper.find("[data-testid=contracts-all]").text();
    expect(rest).toContain("Ends in 45 days");
    expect(rest).toContain("$1,400");
    expect(rest).toContain(en["contracts.wholeCompany"]);
    expect(wrapper.find("[data-testid=contracts-new]").exists()).toBe(true);
  });

  it("asks for what ends soon and hides adding from someone who only reads", async () => {
    const calls = stub({ "GET contracts/": () => json([]), "GET contracts/summary/": () => json(summary) });
    const app = await pageApp("/c/1/contracts?view=ending", ["dashboard.access", "finance.view"]);
    const { wrapper } = mountWithProviders(ContractsPage, { plugins: app.plugins });
    await settle();
    expect(wrapper.find("[data-testid=contracts-new]").exists()).toBe(false);
    expect(wrapper.text()).toContain(en["contracts.empty.filteredTitle"]);
    const list = calls.find((call) => call.path === "contracts/");
    expect(list).toBeDefined();
    const fetchMock = vi.mocked(fetch);
    expect(String(fetchMock.mock.calls.find(([url]) => String(url).includes("contracts/?"))?.[0])).toContain("ending=true");
  });
});

describe("a contract's page", () => {
  it("shows the decision, the term, the files and the payments; keeping it renewing is one tap", async () => {
    const calls = stub({
      "GET contracts/7/": () => json(detail()),
      "POST contracts/7/keep-renewing/": () => json(detail({ renewal_confirmed: true, attention: null })),
      "GET audit/records/": () => json({ count: 0, next: null, previous: null, results: [] }),
    });
    const app = await pageApp("/c/1/contracts/7");
    const { wrapper } = mountWithProviders(ContractPage, { plugins: app.plugins });
    await settle();
    expect(wrapper.find("[data-testid=contract-banner]").text()).toContain("Notice deadline in 10 days");
    expect(wrapper.find("[data-testid=contract-term]").exists()).toBe(true);
    expect(wrapper.find("[data-testid=contract-files]").text()).toContain("Ijara haqi oshirilishi");
    expect(wrapper.find("[data-testid=contract-files]").text()).toContain(en["contracts.fileKind.signed"]);
    expect(wrapper.find("[data-testid=contract-payments]").text()).toContain("Chilonzor dorixonasi ijarasi, 11.2026");
    expect(wrapper.text()).toContain("Ijara: Chilonzor");
    expect(wrapper.find("[data-testid=contract-dates]").text()).toContain(en["contracts.date.notice"]);
    await wrapper.find("[data-testid=contract-keep]").trigger("click");
    await settle();
    expect(calls.some((call) => call.method === "POST" && call.path === "contracts/7/keep-renewing/")).toBe(true);
  });

  it("offers no changes to someone who only reads money", async () => {
    stub({ "GET contracts/7/": () => json(detail({ can: { manage: false } })), "GET audit/records/": () => json({ count: 0, next: null, previous: null, results: [] }) });
    const app = await pageApp("/c/1/contracts/7", ["dashboard.access", "finance.view"]);
    const { wrapper } = mountWithProviders(ContractPage, { plugins: app.plugins });
    await settle();
    expect(wrapper.find("[data-testid=contract-edit]").exists()).toBe(false);
    expect(wrapper.find("[data-testid=contract-menu]").exists()).toBe(false);
    expect(wrapper.find("[data-testid=contract-keep]").exists()).toBe(false);
  });
});

describe("the form", () => {
  it("sends a new lease with a new party and its rent in the forecast", async () => {
    const calls = stub({
      "GET contracts/options/": () => json(options),
      "POST contracts/": () => json(detail({ id: 11, title: "Yunusobod dorixonasi ijarasi" }), 201),
    });
    const app = await pageApp("/c/1/contracts");
    const { inner } = mountWithProviders(ContractFormDialog, { plugins: app.plugins, props: { open: true } });
    await settle();
    const vm = inner.vm as unknown as { $: { setupState: { form: Record<string, unknown>; save: () => Promise<void>; addParty: (name: string) => void } } };
    vm.$.setupState.addParty("Akmal Hasanov (ijara)");
    Object.assign(vm.$.setupState.form, {
      kind: "lease",
      title: "Yunusobod dorixonasi ijarasi",
      branch: 2,
      starts_on: "2026-02-01",
      ends_on: "2026-12-27",
      amount: "1400",
      currency: "USD",
      period: "monthly",
      payment_day: 1,
      in_forecast: true,
      account: 5,
    });
    await vm.$.setupState.save();
    await settle();
    const sent = calls.find((call) => call.method === "POST" && call.path === "contracts/");
    expect(sent?.body).toMatchObject({
      kind: "lease",
      title: "Yunusobod dorixonasi ijarasi",
      counterparty: null,
      counterparty_name: "Akmal Hasanov (ijara)",
      branch: 2,
      amount: "1400",
      currency: "USD",
      payment_day: 1,
      status: "active",
      in_forecast: true,
      account: 5,
    });
    expect((sent?.body as Record<string, unknown>).link_rule).toBeUndefined();
  });

  it("takes over a recurring payment already in Finance", async () => {
    const calls = stub({ "GET contracts/options/": () => json(options), "POST contracts/": () => json(detail(), 201) });
    const app = await pageApp("/c/1/contracts");
    const { inner } = mountWithProviders(ContractFormDialog, { plugins: app.plugins, props: { open: true } });
    await settle();
    const vm = inner.vm as unknown as { $: { setupState: { form: Record<string, unknown>; save: () => Promise<void> } } };
    Object.assign(vm.$.setupState.form, { title: "Chilonzor", party: "p:3", starts_on: "2025-01-22", amount: "9000000", in_forecast: true, source: "link", link_rule: 4 });
    await vm.$.setupState.save();
    await settle();
    const sent = calls.find((call) => call.method === "POST");
    expect(sent?.body).toMatchObject({ counterparty: 3, link_rule: 4, in_forecast: true });
  });

  it("refuses a contract without a name or a start", async () => {
    const calls = stub({ "GET contracts/options/": () => json(options) });
    const app = await pageApp("/c/1/contracts");
    const { inner } = mountWithProviders(ContractFormDialog, { plugins: app.plugins, props: { open: true } });
    await settle();
    const vm = inner.vm as unknown as { $: { setupState: { save: () => Promise<void>; errors: Record<string, string | undefined> } } };
    await vm.$.setupState.save();
    expect(vm.$.setupState.errors.title).toBe(en["contracts.form.errTitle"]);
    expect(vm.$.setupState.errors.starts_on).toBe(en["contracts.form.errStart"]);
    expect(calls.some((call) => call.method === "POST")).toBe(false);
  });
});

describe("settings", () => {
  it("saves the warning days", async () => {
    const calls = stub({
      "GET contracts/settings/": () => json({ remind_days: 30, notice_remind_days: 14 }),
      "PATCH contracts/settings/": (call) => json(call.body),
    });
    const app = await pageApp("/c/1/settings");
    const { wrapper, inner } = mountWithProviders(SettingsPanel, { plugins: app.plugins });
    await settle();
    const vm = inner.vm as unknown as { $: { setupState: { form: Record<string, number> } } };
    vm.$.setupState.form.remind_days = 60;
    await wrapper.find("[data-testid=contracts-settings-save]").trigger("click");
    await settle();
    expect(calls.find((call) => call.method === "PATCH")?.body).toEqual({ remind_days: 60, notice_remind_days: 14 });
  });
});
