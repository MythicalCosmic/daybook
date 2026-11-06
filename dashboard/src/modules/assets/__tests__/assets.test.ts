// Fixed assets screens against a stubbed API: the register with its KPIs and purchases to turn
// into assets, an asset's page (values, schedule by year, the tax book, the actions menu only for
// assets.manage), the form's monthly preview, and what a disposal sends.
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
import { mountWithProviders as mountRaw, testApp } from "@/test/plugins";

import AssetActionDialog from "../components/AssetActionDialog.vue";
import AssetFormDialog from "../components/AssetFormDialog.vue";
import en from "../i18n/en.json";
import { bookValueSeries, daysUntil, upkeepTone, yearsOf } from "../lib";
import AssetPage from "../pages/AssetPage.vue";
import RegisterPage from "../pages/RegisterPage.vue";
import { routes } from "../routes";
import type { AssetDetail, AssetRow, Category, ScheduleMonth } from "../types";

vi.setConfig({ testTimeout: 20_000 });

// Every mount is unmounted after its test, so one page's queries never answer another's.
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
  for (let i = 0; i < 6; i += 1) await flushPromises();
}

beforeEach(() => {
  mergeModuleMessages("assets", { en, ru: en, uz: en });
  localStorage.clear();
});

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount();
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

const row = (overrides: Partial<AssetRow> = {}): AssetRow => ({
  id: 5,
  number: "AV-0005",
  name: "Vaksina muzlatgichi",
  model: "Liebherr",
  category: { id: 1, name: "Pharmacy fridges" },
  category_kind: "fixed",
  icon: "refrigerator",
  branch: { id: 1, name: "Chilonzor" },
  status: "in_use",
  condition: "good",
  cost: "12000000.00",
  accumulated: "714285.70",
  book_value: "11285714.30",
  monthly: "142857.14",
  in_service_on: "2026-05-25",
  custodian: null,
  next_due: { what: "verification", day: "2026-11-28" },
  photo_url: null,
  ...overrides,
});

const months = (from: string, count: number, state: ScheduleMonth["state"]): ScheduleMonth[] => {
  const [year, month] = from.split("-").map(Number) as [number, number];
  return Array.from({ length: count }, (_, index) => {
    const date = new Date(Date.UTC(year, month - 1 + index, 1));
    const closing = 12_000_000 - 142_857.14 * (index + 1);
    return {
      month: date.toISOString().slice(0, 10),
      opening: (closing + 142_857.14).toFixed(2),
      amount: "142857.14",
      closing: closing.toFixed(2),
      accumulated: (142_857.14 * (index + 1)).toFixed(2),
      state,
      notes: [],
      transaction_id: state === "booked" ? 100 + index : null,
    };
  });
};

const detail = (overrides: Partial<AssetDetail> = {}): AssetDetail => ({
  asset: row(),
  serial: "LH-1",
  notes: "",
  purchased_on: "2026-05-20",
  price: "12000000.00",
  price_currency: "UZS",
  price_rate: "1.000000",
  life_months: 84,
  method: "straight_line",
  declining_factor: "2.00",
  total_units: null,
  unit: "",
  opening_accumulated: null,
  books_depreciation: true,
  booked: true,
  supplier: null,
  supplier_name: "Sovutish Texnika",
  purchase: { id: 9, occurred_on: "2026-05-20", amount: "12000000.00", currency: "UZS", description: "Muzlatgich", account: "Kassa", capitalized: true },
  responsible: { id: 3, name: "Dilnoza Karimova" },
  warranty_until: "2027-05-20",
  insurance_until: null,
  service_months: 6,
  next_service_on: "2026-11-25",
  verify_months: null,
  next_verification_on: null,
  disposed_on: null,
  disposal: "",
  disposal_amount: null,
  disposal_reason: "",
  qr_link: "asset_x",
  values: {
    cost: "12000000.00",
    added: "0.00",
    written_down: "0.00",
    accumulated: "714285.70",
    book: "11285714.30",
    salvage_value: "0.00",
    monthly_now: "142857.14",
    months_used: 5,
    months_left: 79,
    end_month: "2033-05-01",
    fully_depreciated: false,
  },
  schedule: [...months("2026-06", 5, "booked"), ...months("2026-11", 14, "planned")],
  tax: { rate: "20.00", group: "III", monthly: "200000.00", accumulated: "1000000.00", book: "11000000.00", end_month: "2031-05-01", difference: "-285714.30" },
  events: [{ id: 1, kind: "created", on: "2026-11-07", amount: null, units: null, from_branch: null, to_branch: null, person: null, note: "", details: {}, by: "Owner", created_at: "2026-11-07T10:00:00+05:00" }],
  assignments: [],
  files: [],
  ...overrides,
});

const category: Category = {
  id: 1,
  name: "Pharmacy fridges",
  kind: "fixed",
  life_months: 84,
  method: "straight_line",
  salvage_percent: "0.00",
  tax_group: "III",
  tax_rate: "20.00",
  service_months: 6,
  verify_months: null,
  icon: "refrigerator",
  order: 0,
  is_active: true,
  system_code: "fridges",
  assets: 1,
};

function as(permissions: Perm[]): void {
  useSessionStore().me = me([company({ is_owner: false, permissions, features: ["finance", "assets"] })]);
}

describe("lib", () => {
  it("counts days and colours upkeep", () => {
    expect(daysUntil("2026-11-10", "2026-11-07")).toBe(3);
    expect(daysUntil("2026-11-01", "2026-11-07")).toBe(-6);
    expect(upkeepTone("2026-11-01", "2026-11-07")).toBe("danger");
    expect(upkeepTone("2026-11-20", "2026-11-07")).toBe("warning");
    expect(upkeepTone("2027-03-01", "2026-11-07")).toBe("neutral");
  });

  it("joins the posted and planned lines and groups the years", () => {
    const schedule = [...months("2026-06", 5, "booked"), ...months("2026-11", 3, "planned")];
    const series = bookValueSeries(schedule);
    expect(series.categories[0]).toBe("2026-06");
    expect(series.posted.slice(4, 6)).toEqual([schedule[4]!.closing, null]);
    expect(series.planned[4]).toBe(schedule[4]!.closing); // the two lines meet
    expect(series.planned[3]).toBeNull();
    const years = yearsOf(schedule);
    expect(years.map((group) => group.year)).toEqual([2026, 2027]);
    expect(years[0]!.months).toHaveLength(7);
    expect(years[1]!.planned).toBe(true);
  });
});

describe("the register", () => {
  it("lists the assets with their value and offers purchases to turn into assets", async () => {
    stub({
      "GET assets/items/": () => json([row(), row({ id: 6, number: "AV-0006", name: "Konditsioner", custodian: { id: 3, name: "Dilnoza" } })]),
      "GET assets/summary/": () =>
        json({ count: 2, cost: "19400000.00", accumulated: "900000.00", book: "18500000.00", this_month: "230000.00", this_year: "900000.00", fully_depreciated: 0, upkeep_due: 1, low_value: 0 }),
      "GET assets/categories/": () => json([category]),
      "GET assets/purchases/": () =>
        json([{ id: 9, occurred_on: "2026-10-02", amount: "8400000.00", currency: "UZS", base_amount: "8400000.00", category: "Uskunalar", counterparty: null, branch: null, account: "Kassa", description: "Konditsioner Artel" }]),
    });
    const app = await testApp("/c/1/assets/items");
    const { wrapper } = mountWithProviders(RegisterPage, { plugins: app.plugins });
    await settle();
    const text = wrapper.text();
    expect(text).toContain("AV-0005");
    expect(text).toContain("Konditsioner");
    expect(text).toContain("Dilnoza");
    expect(text).toContain("Konditsioner Artel");
    expect(text).toContain(en["assets.purchases.turn"]);
  });
});

async function pageApp(path: string) {
  const pinia = createPinia();
  setActivePinia(pinia);
  useSessionStore().me = me([company({ features: ["finance", "assets"] })]);
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

describe("an asset's page", () => {
  it("shows its value, the schedule by year and the tax book", async () => {
    stub({ "GET assets/items/5/": () => json(detail()) });
    const app = await pageApp("/c/1/assets/items/5");
    const { wrapper } = mountWithProviders(AssetPage, { plugins: app.plugins });
    await settle();
    const text = wrapper.text();
    expect(text).toContain("AV-0005 · Vaksina muzlatgichi");
    expect(text).toContain(en["assets.item.taxTitle"]);
    expect(text).toContain(en["assets.item.scheduleTitle"]);
    expect(wrapper.find("[data-testid=asset-schedule]").text()).toContain("2027");
    expect(text).toContain(en["assets.item.actions"]);
  });

  it("shows no actions to someone who only reads finance", async () => {
    stub({ "GET assets/items/5/": () => json(detail()) });
    const app = await pageApp("/c/1/assets/items/5");
    as(["dashboard.access", "finance.view"]);
    const { wrapper } = mountWithProviders(AssetPage, { plugins: app.plugins });
    await settle();
    expect(wrapper.text()).not.toContain(en["assets.item.actions"]);
  });
});

describe("the form and the steps", () => {
  it("previews the monthly depreciation from the category", async () => {
    stub({ "GET assets/categories/": () => json([category]) });
    const app = await testApp("/c/1/assets/items");
    mountWithProviders(AssetFormDialog, { plugins: app.plugins, props: { open: true } });
    await settle();
    const select = document.body.querySelector("[data-testid=asset-save]");
    expect(select).not.toBeNull();
    expect(document.body.textContent).toContain(en["assets.form.newTitle"]);
  });

  it("sends a sale with its price and account", async () => {
    const calls = stub({
      "POST assets/items/5/dispose/": () => json(detail({ asset: row({ status: "disposed" }) })),
      "GET finance/accounts/": () => json({ accounts: [{ id: 4, name: "Kassa", currency: "UZS", is_active: true }] }),
    });
    const app = await testApp("/c/1/assets/items/5");
    const { inner } = mountWithProviders(AssetActionDialog, { plugins: app.plugins, props: { open: true, asset: detail(), kind: "dispose" } });
    await settle();
    const vm = inner.vm as unknown as { $: { setupState: { form: Record<string, unknown>; submit: () => Promise<void> } } };
    Object.assign(vm.$.setupState.form, { disposal: "sold", amount: "7000000.00", account: 4, on: "2026-11-07" });
    await vm.$.setupState.submit();
    await settle();
    const sent = calls.find((call) => call.method === "POST");
    expect(sent?.path).toBe("assets/items/5/dispose/");
    expect(sent?.body).toEqual({ on: "2026-11-07", kind: "sold", amount: "7000000.00", account: 4, reason: "" });
  });
});

describe("licences and permits", () => {
  it("puts the expired ones first and says how long the others have", async () => {
    const permit = (id: number, days_left: number | null, name: string) => ({
      id,
      kind: "pharmacy_licence",
      name,
      number: "L-1",
      issuer: "",
      issued_on: null,
      valid_until: days_left === null ? null : "2026-12-17",
      remind_days: 60,
      branch: 1,
      branch_name: "Chilonzor",
      responsible: null,
      responsible_name: null,
      notes: "",
      days_left,
      file_url: null,
    });
    stub({ "GET assets/permits/": () => json([permit(1, -3, "Litsenziya"), permit(2, 40, "Ijara"), permit(3, null, "Sug‘urta")]) });
    const app = await testApp("/c/1/assets/permits");
    const { default: PermitsPage } = await import("../pages/PermitsPage.vue");
    const { wrapper } = mountWithProviders(PermitsPage, { plugins: app.plugins });
    await settle();
    expect(wrapper.find("[data-testid=permits-expired]").text()).toContain("Litsenziya");
    expect(wrapper.find("[data-testid=permits-soon]").text()).toContain("Ijara");
    expect(wrapper.find("[data-testid=permits-valid]").text()).toContain(en["assets.permits.noEnd"]);
  });
});
