// Stock screens against a stubbed API: the quantity and expiry helpers, the catalogue with its
// marks (cost columns only with finance.view), the import wizard's dry run, a receipt's lines,
// warnings and payable (posting only for stock.manage), the blind count, the expiry board's
// buckets, the controlled register, and what Settings › Stock sends.
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

import ImportWizard from "../components/ImportWizard.vue";
import SettingsPanel from "../components/SettingsPanel.vue";
import en from "../i18n/en.json";
import ru from "../i18n/ru.json";
import uz from "../i18n/uz.json";
import { daysUntil, expiryTone, packsAndParts, partsOf, previousMonth, qtyText } from "../lib";
import CountPage from "../pages/CountPage.vue";
import ExpiryPage from "../pages/ExpiryPage.vue";
import DefekturaPage from "../pages/DefekturaPage.vue";
import JournalsPage from "../pages/JournalsPage.vue";
import AttentionWidget from "../widgets/AttentionWidget.vue";
import ProductsPage from "../pages/ProductsPage.vue";
import ReceiptPage from "../pages/ReceiptPage.vue";
import { routes } from "../routes";
import type { CountDetail, ExpiryBoard, Product, ReceiptDetail, StockSettings } from "../types";

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
  query: string;
  body: unknown;
  form: FormData | null;
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
      const [path, query = ""] = url.replace(/^.*\/api\/v1\/owner\/companies\/1\//, "").split("?") as [string, string?];
      const body = init?.body && typeof init.body === "string" ? JSON.parse(init.body) : undefined;
      const form = init?.body instanceof FormData ? init.body : null;
      const call = { method: init?.method ?? "GET", path, query, body, form };
      calls.push(call);
      return routesByCall[`${call.method} ${path}`]?.(call) ?? json({ detail: "Not found." }, 404);
    }),
  );
  return calls;
}

async function settle(): Promise<void> {
  for (let i = 0; i < 8; i += 1) await flushPromises();
}

const t = (key: string, named: Record<string, unknown> = {}, plural?: number): string => {
  const text = (en as Record<string, string>)[key] ?? key;
  const forms = text.split(" | ");
  const chosen = forms.length > 1 && plural !== undefined ? forms[plural === 1 ? 0 : 1]! : forms[0]!;
  return chosen.replace(/\{(\w+)\}/g, (_, name: string) => String(named[name] ?? ""));
};

beforeEach(() => {
  mergeModuleMessages("stock", { en, ru: en, uz: en });
  localStorage.clear();
});

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount();
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

function as(permissions: Perm[]): void {
  useSessionStore().me = me([company({ is_owner: false, permissions, features: ["finance", "stock"] })]);
}

async function pageApp(path: string, permissions: Perm[] | null = null) {
  const pinia = createPinia();
  setActivePinia(pinia);
  useSessionStore().me = me([permissions ? company({ is_owner: false, permissions, features: ["finance", "stock"] }) : company({ features: ["finance", "stock"] })]);
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

const product = (overrides: Partial<Product> = {}): Product => ({
  id: 7,
  name: "Amoksitsillin 500 mg kapsula №16",
  trade_name: "",
  inn: "amoxicillin",
  kind: "medicine",
  dosage_form: "capsule",
  strength: "500 mg",
  units_per_pack: 2,
  part_label: "blister",
  manufacturer: { id: 1, name: "Farm Zavod" },
  category: null,
  rx_required: true,
  e_rx_group: true,
  control_class: "none",
  restricted_channel: false,
  storage: "room",
  light_sensitive: false,
  barcode: "4780000000017",
  sku: "",
  mxik_code: "",
  package_code: "",
  registration_number: "",
  registration_until: null,
  marking_required: false,
  vat_percent: null,
  socially_significant: false,
  mandatory_list: true,
  reference_price: null,
  reference_price_on: null,
  sale_price: "12400.00",
  part_price: null,
  effective_part_price: "6200.00",
  track_stock: true,
  is_active: true,
  quantity: "7.000",
  nearest_expiry: "2026-11-20",
  ...overrides,
});

describe("lib", () => {
  it("says quantities in packs and parts", () => {
    expect(packsAndParts("7.000", 2, "blister", t)).toBe("3 packs 1 blister");
    expect(packsAndParts(6, 2, "blister", t)).toBe("3 packs");
    expect(packsAndParts(1, 2, "", t)).toBe("1 part");
    expect(packsAndParts(1, 1, "", t)).toBe("1 pack");
    expect(packsAndParts("-3", 2, "blister", t)).toBe("−1 pack 1 blister");
    expect(qtyText("2.500")).toBe("2.5");
    expect(partsOf(3, 1, 2)).toBe(7);
  });

  it("colours expiry and finds the month to close", () => {
    expect(daysUntil("2026-11-10", "2026-11-07")).toBe(3);
    expect(expiryTone("2026-11-06", "2026-11-07")).toBe("danger");
    expect(expiryTone("2026-11-30", "2026-11-07")).toBe("warning");
    expect(expiryTone("2027-01-15", "2026-11-07")).toBe("info");
    expect(expiryTone("2027-11-07", "2026-11-07")).toBe("neutral");
    expect(previousMonth("2026-11-07")).toBe("2026-10");
    expect(previousMonth("2026-01-03")).toBe("2025-12");
  });

  it("has every text in all three languages, and nothing empty", () => {
    const keys = Object.keys(en).sort();
    expect(Object.keys(uz).sort()).toEqual(keys);
    expect(Object.keys(ru).sort()).toEqual(keys);
    for (const dictionary of [en, uz, ru] as Array<Record<string, string>>) for (const value of Object.values(dictionary)) expect(value.trim()).not.toBe("");
    // Uzbek writes o‘ and g‘ with U+2018 and the tutuq belgisi with U+2019, never ' or `.
    for (const value of Object.values(uz as Record<string, string>)) expect(value).not.toMatch(/['`]/);
    expect((uz as Record<string, string>)["stock.drawer.analogsTitle"]).toBe("Ta’sir etuvchi moddasi, shakli va dozasi bir xil");
    expect((ru as Record<string, string>)["stock.drawer.analogsTitle"]).toBe("То же МНН, форма и дозировка");
  });
});

describe("the catalogue", () => {
  it("lists medicines with their marks, and the cost only with finance.view", async () => {
    stub({
      "GET stock/products/": () => json({ count: 2, results: [product(), product({ id: 8, name: "Paratsetamol 500 mg tabletka №20", rx_required: false, storage: "cold", mandatory_list: false, quantity: "0.000" })] }),
      "GET stock/categories/": () => json([]),
    });
    const app = await pageApp("/c/1/stock/products", ["dashboard.access", "stock.operate"]);
    const { wrapper } = mountWithProviders(ProductsPage, { plugins: app.plugins });
    await settle();
    const text = wrapper.text();
    expect(text).toContain("Amoksitsillin 500 mg kapsula №16");
    expect(text).toContain("3 packs 1 blister");
    expect(wrapper.find("[data-badge=rx]").exists()).toBe(true);
    expect(wrapper.find("[data-badge=mandatory]").exists()).toBe(true);
    expect(wrapper.find("[data-badge=cold]").exists()).toBe(true);
    expect(text).not.toContain(en["stock.col.cost"]);
    expect(text).not.toContain(en["stock.products.import"]);
  });

  it("shows the last cost to someone with finance.view", async () => {
    stub({
      "GET stock/products/": () => json({ count: 1, results: [product({ cost_price: "10340.00" })] }),
      "GET stock/categories/": () => json([]),
    });
    const app = await pageApp("/c/1/stock/products");
    const { wrapper } = mountWithProviders(ProductsPage, { plugins: app.plugins });
    await settle();
    expect(wrapper.text()).toContain(en["stock.col.cost"]);
    expect(wrapper.text()).toContain(en["stock.products.import"]);
  });
});

describe("the import wizard", () => {
  it("checks the file with a dry run first, then imports with the columns it found", async () => {
    const result = (dry: boolean) => ({
      dry_run: dry,
      columns: ["Nomi", "Shtrix-kod"],
      mapping: { Nomi: "name", "Shtrix-kod": "barcode" },
      created: 2,
      updated: 1,
      skipped: 1,
      rows: [
        { row: 2, action: "create", name: "Analgin 500 mg tabletka №10", product_id: null, errors: [] },
        { row: 3, action: "update", name: "Paratsetamol 500 mg tabletka №20", product_id: 8, errors: [] },
        { row: 4, action: "skip", name: "", product_id: null, errors: ["No name."] },
      ],
    });
    const calls = stub({ "POST stock/products/import/": (call) => json(result(call.form?.get("dry_run") === "true")) });
    const app = await testApp("/c/1/stock/products");
    const { inner } = mountWithProviders(ImportWizard, { plugins: app.plugins, props: { open: true } });
    await settle();
    const state = (inner.vm as unknown as { $: { setupState: { files: File[]; check: () => Promise<void>; run: () => Promise<void>; step: string } } }).$.setupState;
    state.files = [new File(["Nomi;Shtrix-kod\n"], "katalog.csv", { type: "text/csv" })];
    await state.check();
    await settle();
    expect(calls).toHaveLength(1);
    expect(calls[0]!.form?.get("dry_run")).toBe("true");
    expect(state.step).toBe("check");
    const rows = document.body.querySelector("[data-testid=import-rows]")!.textContent ?? "";
    expect(rows).toContain("Analgin 500 mg tabletka №10");
    expect(rows).toContain("No name.");
    expect(document.body.querySelector("[data-testid=import-counts]")!.textContent).toContain("2");
    await state.run();
    await settle();
    expect(calls[1]!.form?.get("dry_run")).toBe("false");
    expect(JSON.parse(String(calls[1]!.form?.get("mapping")))).toEqual({ Nomi: "name", "Shtrix-kod": "barcode" });
    expect(state.step).toBe("done");
  });
});

const receipt = (overrides: Partial<ReceiptDetail["receipt"]> = {}): ReceiptDetail => ({
  receipt: {
    id: 12,
    number: "KR-CHL-0042",
    status: "posted",
    branch: { id: 1, name: "Chilonzor", code: "CHL" },
    supplier: { id: 3, name: "Ko‘kterak Farm Distribyutor" },
    supplier_invoice_number: "N-118",
    supplier_invoice_date: "2026-10-05",
    currency: "UZS",
    due_on: "2026-11-04",
    note: "",
    e_invoice_ref: "",
    lines_count: 1,
    warnings: ["short_shelf_life"],
    received_by: { id: 4, name: "Ali Valiyev", photo_url: null },
    posted_by: { id: 2, name: "Bekzod Mirzayev", photo_url: null },
    submitted_at: "2026-10-05T10:00:00+05:00",
    posted_at: "2026-10-05T11:00:00+05:00",
    created_at: "2026-10-05T09:00:00+05:00",
    file_url: null,
    total: "103400.00",
    vat_total: "0.00",
    debt_id: 55,
    debt_status: "open",
    debt_paid: "0.00",
    void_reason: "",
    ...overrides,
  },
  lines: [
    {
      id: 90,
      product: { id: 7, name: "Amoksitsillin 500 mg kapsula №16" },
      units_per_pack: 2,
      rx_required: true,
      control_class: "none",
      series: "230415",
      expires_on: "2027-02-28",
      made_on: null,
      packs: "10.000",
      quantity: "20.000",
      vat_percent: null,
      retail_price: "12400.00",
      price_cap: "12400.00",
      supplier_rx: null,
      warnings: ["short_shelf_life"],
      unit_cost: "10340.00",
      total: "103400.00",
      batch_id: 31,
    },
  ],
});

describe("a goods receipt", () => {
  it("shows its lines, warnings and the payable it opened", async () => {
    stub({ "GET stock/receipts/12/": () => json(receipt()) });
    const app = await pageApp("/c/1/stock/receipts/12");
    const { wrapper } = mountWithProviders(ReceiptPage, { plugins: app.plugins });
    await settle();
    const text = wrapper.text();
    expect(text).toContain("Receipt KR-CHL-0042");
    expect(text).toContain("Series 230415");
    expect(text).toContain("10 packs");
    expect(wrapper.find("[data-warning=short_shelf_life]").exists()).toBe(true);
    const payable = wrapper.find("[data-testid=receipt-payable] a");
    expect(payable.attributes("href")).toBe("/c/1/finance/debts?debt=55");
  });

  it("lets a pharmacist add lines and send it, but not post it or see its cost", async () => {
    const detail = receipt({ status: "draft", number: "", debt_id: undefined, debt_status: undefined, debt_paid: undefined, total: undefined, vat_total: undefined });
    for (const line of detail.lines) {
      delete line.unit_cost;
      delete line.total;
    }
    stub({ "GET stock/receipts/12/": () => json(detail) });
    const app = await pageApp("/c/1/stock/receipts/12", ["dashboard.access", "stock.operate"]);
    const { wrapper } = mountWithProviders(ReceiptPage, { plugins: app.plugins });
    await settle();
    expect(wrapper.text()).toContain("Draft receipt #12");
    expect(wrapper.find("[data-testid=receipt-add-line]").exists()).toBe(true);
    expect(wrapper.find("[data-testid=receipt-post]").exists()).toBe(false);
    expect(wrapper.text()).not.toContain(en["stock.batch.cost"]);
    expect(wrapper.find("[data-testid=receipt-payable]").exists()).toBe(false);
  });
});

const count = (status: CountDetail["count"]["status"], reviewed: boolean): CountDetail => ({
  count: {
    id: 5,
    kind: "full",
    status,
    branch: { id: 1, name: "Chilonzor", code: "CHL" },
    category: null,
    lines_count: 1,
    counted_count: status === "open" ? 0 : 1,
    started_by: null,
    created_at: "2026-11-07T09:00:00+05:00",
    submitted_at: null,
    applied_at: null,
  },
  lines: [
    {
      id: 41,
      product: { id: 7, name: "Amoksitsillin 500 mg kapsula №16" },
      units_per_pack: 2,
      part_label: "blister",
      batch_id: 31,
      series: "230415",
      expires_on: "2027-02-28",
      counted: status === "open" ? null : "6.000",
      ...(reviewed ? { expected: "8.000", difference: "-2.000", value_difference: "-10340.00" } : {}),
    },
  ],
});

describe("a stock count", () => {
  it("is blind while open: no expected quantity, packs and parts to type", async () => {
    stub({ "GET stock/counts/5/": () => json(count("open", false)) });
    const app = await pageApp("/c/1/stock/counts/5", ["dashboard.access", "stock.operate"]);
    const { wrapper } = mountWithProviders(CountPage, { plugins: app.plugins });
    await settle();
    const table = wrapper.find("[data-testid=count-lines]").text();
    expect(table).toContain("230415");
    expect(table).not.toContain(en["stock.count.expected"]);
    expect(wrapper.findAll("[data-line='41'] input").length).toBe(2);
  });

  it("shows what was expected and the difference once counted", async () => {
    stub({ "GET stock/counts/5/": () => json(count("submitted", true)) });
    const app = await pageApp("/c/1/stock/counts/5");
    const { wrapper } = mountWithProviders(CountPage, { plugins: app.plugins });
    await settle();
    const table = wrapper.find("[data-testid=count-lines]").text();
    expect(table).toContain(en["stock.count.expected"]);
    expect(table).toContain("4 packs");
    expect(table).toContain("−1 pack");
    expect(wrapper.find("[data-testid=count-apply]").exists()).toBe(true);
  });
});

const board = (withCost: boolean): ExpiryBoard => {
  const row = (id: number, expired: boolean, days: number) => ({
    id,
    batch_id: 100 + id,
    branch_id: 1,
    branch: "Chilonzor",
    product_id: 7,
    product: "Amoksitsillin 500 mg kapsula №16",
    series: `S-${id}`,
    expires_on: expired ? "2026-11-01" : "2026-11-27",
    days_left: days,
    expired,
    status: "sellable" as const,
    quantity: "4.000",
    units_per_pack: 2,
    retail_value: "24800.00",
    ...(withCost ? { value: "20680.00" } : {}),
  });
  const bucket = (key: "expired" | "d30" | "d60" | "d90", days: number, rows: ReturnType<typeof row>[]) => ({
    key,
    days,
    count: rows.length,
    retail_value: "24800.00",
    ...(withCost ? { value: "20680.00" } : {}),
    rows,
  });
  return { as_of: "2026-11-07", within: 90, buckets: [bucket("expired", 0, [row(1, true, -6)]), bucket("d30", 30, [row(2, false, 20)]), bucket("d60", 60, []), bucket("d90", 90, [])] };
};

describe("the expiry board", () => {
  it("shows the buckets with their value and every batch", async () => {
    stub({ "GET stock/expiry/": () => json(board(false)) });
    const app = await pageApp("/c/1/stock/expiry", ["dashboard.access", "stock.operate"]);
    const { wrapper } = mountWithProviders(ExpiryPage, { plugins: app.plugins });
    await settle();
    const buckets = wrapper.find("[data-testid=expiry-buckets]").text();
    expect(buckets).toContain(en["stock.expiry.bucket.expired"]);
    expect(buckets).toContain(en["stock.expiry.bucket.d30"]);
    expect(buckets).not.toContain(en["stock.expiry.atCost"]);
    expect(wrapper.text()).toContain("S-1");
    expect(wrapper.text()).toContain("2 packs");
  });
});

describe("the controlled register", () => {
  it("lists the month at a licensed pharmacy and offers to close it", async () => {
    stub({
      "GET stock/settings/": () => json({ rx_log: true }),
      "GET stock/journals/controlled/": () =>
        json({
          branch: { id: 1, name: "Yunusobod", code: "YNS" },
          month: "2026-10-01",
          closed: false,
          close_by: "2026-11-03",
          branches: [{ id: 1, name: "Yunusobod", code: "YNS" }],
          rows: [
            {
              id: 9,
              product_id: 9,
              product: "Tramadol 50 mg kapsula №10",
              inn: "tramadol",
              control_class: "narcotic",
              units_per_pack: 1,
              opening: "10.000",
              received: "20.000",
              issued: "8.000",
              written_off: "2.000",
              adjusted: "0.000",
              closing: "20.000",
              unrecorded_issues: 0,
              period_id: null,
              counted: null,
              difference: null,
              closed_at: null,
              reported_on: null,
            },
          ],
        }),
    });
    const app = await pageApp("/c/1/stock/journals?month=2026-10", ["dashboard.access", "stock.controlled"]);
    const { wrapper } = mountWithProviders(JournalsPage, { plugins: app.plugins });
    await settle();
    const table = wrapper.find("[data-testid=controlled-rows]").text();
    expect(table).toContain("Tramadol 50 mg kapsula №10");
    expect(table).toContain("20");
    expect(table).not.toContain("20 packs");
    expect(wrapper.find("[data-testid=close-month]").attributes("disabled")).toBeUndefined();
  });
});

describe("defektura", () => {
  it("lists the requests and changes their status", async () => {
    const calls = stub({
      "GET stock/defektura/": () =>
        json([
          {
            id: 3,
            branch_ref: { id: 1, name: "Chilonzor", code: "CHL" },
            product_ref: null,
            name: "Insulin glargin 100 TB/ml",
            packs: "1.000",
            source: "counter",
            status: "open",
            customer_phone: "+998901112233",
            requested_at: "2026-11-07T10:00:00+05:00",
            requested_by: { id: 4, name: "Ali Valiyev", photo_url: null },
          },
        ]),
      "PATCH stock/defektura/3/": () => json({}),
    });
    const app = await pageApp("/c/1/stock/defektura", ["dashboard.access", "stock.operate"]);
    const { wrapper } = mountWithProviders(DefekturaPage, { plugins: app.plugins });
    await settle();
    expect(wrapper.text()).toContain("Insulin glargin 100 TB/ml");
    expect(wrapper.text()).toContain("Ali Valiyev");
    const vm = wrapper.findComponent(DefekturaPage).vm as unknown as { $: { setupState: { change: (row: unknown, value: string) => Promise<void> } } };
    await vm.$.setupState.change({ id: 3, status: "open" }, "ordered");
    await settle();
    expect(calls.find((call) => call.method === "PATCH")?.body).toEqual({ status: "ordered" });
  });
});

describe("the Overview tile", () => {
  it("lists only what needs doing, each with its page", async () => {
    stub({
      "GET stock/summary/": () =>
        json({
          products: 60,
          low: 2,
          negative: 0,
          expiring_30d: 8,
          expiring_30d_retail: "420000.00",
          expired: 3,
          stock_retail_value: "88000000.00",
          receipts_to_post: 1,
          drafts: 1,
          writeoffs_to_approve: 0,
          transfers_disputed: 1,
          transfers_incoming: 0,
          recalls_open: 0,
          mandatory_missing: 1,
          controlled_branches: 1,
          estimate: true,
        }),
    });
    const app = await testApp("/c/1");
    const { wrapper } = mountWithProviders(AttentionWidget, { plugins: app.plugins, props: { companyId: 1 } });
    await settle();
    const text = wrapper.text();
    expect(text).toContain("1 receipt to post");
    expect(text).toContain("1 transfer arrived short");
    expect(text).toContain("2 items below their minimum");
    expect(text).not.toContain("write-off");
    expect(wrapper.find("a[href='/c/1/stock/levels?mandatory=1']").exists()).toBe(true);
  });
});

describe("Settings › Stock", () => {
  it("shows the pricing rules, first match first", async () => {
    const settingsStub = { expiry_steps: [90, 60, 30], rx_keep_months: { regular: 3, benefit: 36, narcotic: 60, psychotropic: 12, listed: 12 } };
    stub({
      "GET stock/settings/": () => json(settingsStub),
      "GET stock/pricing-rules/": () =>
        json([
          { id: 1, category: 2, category_name: "Vitaminlar", cost_from: null, cost_to: null, markup_percent: "40.00", order: 0, is_active: true },
          { id: 2, category: null, category_name: null, cost_from: "100000.00", cost_to: null, markup_percent: "18.00", order: 1, is_active: true },
        ]),
      "GET stock/categories/": () => json([]),
    });
    const app = await testApp("/c/1/settings/stock");
    as(["dashboard.access", "stock.manage"]);
    const { wrapper } = mountWithProviders(SettingsPanel, { plugins: app.plugins });
    await settle();
    const rules = wrapper.find("[data-testid=pricing-rules]").text();
    expect(rules.indexOf("Vitaminlar")).toBeLessThan(rules.indexOf(en["stock.rules.anyCategory"]));
    expect(rules).toContain("40.00 %");
    expect(rules).toContain("18.00 %");
  });

  it("sends every setting, the expiry steps as day counts", async () => {
    const settings: StockSettings = {
      expiry_steps: [90, 60, 30],
      min_shelf_days: 180,
      fefo_strict: true,
      allow_negative: true,
      default_markup_percent: "25.00",
      rx_max_markup_percent: "20.00",
      social_max_markup_percent: "10.00",
      cap_enforced: true,
      price_rounding: "100.00",
      price_jump_percent: "10.00",
      writeoff_approval: true,
      show_other_branches: true,
      camera_scanning: true,
      rx_log: true,
      count_tolerance: "50000.00",
      destroy_within_days: 30,
      destroy_commission_min: 5,
      rx_keep_months: { regular: 3, benefit: 36, narcotic: 60, psychotropic: 12, listed: 12 },
      rx_destroy_commission_min: 3,
      narcotic_rx_valid_days: 7,
      psychotropic_rx_valid_months: 1,
      psychotropic_stock_months: 1,
      controlled_close_day: 3,
      controlled_report_days: 3,
    };
    const calls = stub({ "GET stock/settings/": () => json(settings), "PATCH stock/settings/": () => json(settings) });
    const app = await testApp("/c/1/settings/stock");
    as(["dashboard.access", "stock.manage"]);
    const { inner } = mountWithProviders(SettingsPanel, { plugins: app.plugins });
    await settle();
    const state = (inner.vm as unknown as { $: { setupState: { form: Record<string, unknown>; save: () => Promise<void> } } }).$.setupState;
    state.form.steps = "30, 90 60";
    await state.save();
    await settle();
    const sent = calls.find((call) => call.method === "PATCH")?.body as Record<string, unknown>;
    expect(sent.expiry_steps).toEqual([90, 60, 30]);
    expect(sent.rx_max_markup_percent).toBe("20");
    expect(sent.rx_keep_months).toEqual({ regular: 3, benefit: 36, narcotic: 60, psychotropic: 12, listed: 12 });
    expect(Object.keys(sent).sort()).toEqual(Object.keys(settings).sort());
  });
});
