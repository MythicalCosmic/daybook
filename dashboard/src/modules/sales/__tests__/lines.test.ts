// Sale lines from the cash-register program (plan §14.7): the Lines page, the Import page with the
// match list and the profile mapper, the cashier codes and the settings choice.
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Perm } from "@/core/perms";
import { mergeModuleMessages, setLanguage } from "@/i18n";
import { useSessionStore } from "@/stores/session";
import { company, json, me } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import { salesApi } from "../api";
import LinesPage from "../pages/LinesPage.vue";
import ImportPage from "../pages/ImportPage.vue";
import PosCashiersPanel from "../components/PosCashiersPanel.vue";
import { packsAndParts } from "../format";
import en from "../i18n/en.json";
import ru from "../i18n/ru.json";
import uz from "../i18n/uz.json";
import type { LineCode, SaleLine, SalesImport } from "../types";

interface Call {
  method: string;
  url: string;
  body: unknown;
}

function stub(routes: Record<string, (call: Call) => Response | Promise<Response>>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const body = init?.body && typeof init.body === "string" ? JSON.parse(init.body) : init?.body;
      const call = { method: init?.method ?? "GET", url: input, body };
      calls.push(call);
      const path = input.replace("/api/v1/owner/companies/1/", "").split("?")[0]!;
      return routes[`${call.method} ${path}`]?.(call) ?? json({ detail: "Not found." }, 404);
    }),
  );
  return calls;
}

const page = <T>(results: T[]) => ({ count: results.length, next: null, previous: null, results });

const options = (salesLines: "none" | "import" = "import") => ({
  currency: "UZS",
  settings: { mode: "shift_totals", blind_cash_count: true, cash_tolerance: "5000.00", business_day_ends_at: "04:00", sales_lines: salesLines },
  today: "2026-10-21",
  branches: [{ id: 1, name: "Chilonzor", code: "CHL" }],
  registers: [],
  methods: [],
  cashiers: [{ id: 16, name: "Madina Saidova", branch_ids: [1] }],
  receivers: [],
  categories: [],
  accounts: [],
});

function line(extra: Partial<SaleLine> = {}): SaleLine {
  return {
    id: 1,
    status: "matched",
    receipt: { id: 9, number: "101", kind: "sale", source: "import", sold_at: "2026-10-21T05:15:00Z", business_day: "2026-10-21", payment: "Naqd" },
    branch: { id: 1, name: "Chilonzor", code: "CHL" },
    cashier: { id: 16, name: "Madina Saidova", code: "" },
    line_number: 1,
    code: "4780000000024",
    name: "Amoksitsillin",
    product: { id: 5, name: "Amoksitsillin 500 mg kapsula №16", rx_required: true },
    batch: null,
    series: "",
    unit: "pack",
    quantity: "3.000",
    parts_per_pack: 2,
    price: "13500.00",
    discount: "0.00",
    total: "20250.00",
    pack_price: "13500.00",
    cost: "15000.00",
    cap: "12000.00",
    over_cap: true,
    rx_number: "R-778",
    ...extra,
  };
}

/** After `testApp` (which signs in as the owner): a non-owner holding these permissions. */
function as(permissions: Perm[]): void {
  useSessionStore().me = me([company({ is_owner: false, permissions })]);
}

beforeEach(() => {
  mergeModuleMessages("sales", { en, ru, uz });
});

afterEach(async () => {
  vi.unstubAllGlobals();
  await setLanguage("en");
  document.body.innerHTML = "";
});

describe("sale line display rules", () => {
  it("reads parts as whole packs and the parts left over", () => {
    expect(packsAndParts("7", 2)).toEqual({ packs: 3, rest: 1 });
    expect(packsAndParts("4.000", 2)).toEqual({ packs: 2, rest: 0 });
    expect(packsAndParts("1", 3)).toEqual({ packs: 0, rest: 1 });
    expect(packsAndParts("2", 1)).toEqual({ packs: 2, rest: 0 });
  });

  it("has every key in every language, with Uzbek apostrophes as ‘ and ’", () => {
    const keys = Object.keys(en).filter((key) => /^sales\.(import|lines|match|pos|profile|settings\.lines)\./.test(key));
    expect(keys.length).toBeGreaterThan(150);
    for (const key of keys) {
      expect((ru as Record<string, string>)[key], key).toBeTruthy();
      expect((uz as Record<string, string>)[key], key).toBeTruthy();
      expect((uz as Record<string, string>)[key], key).not.toMatch(/['`]/);
    }
  });
});

describe("sale lines API", () => {
  it("uploads a file with its profile and matches a code", async () => {
    const calls = stub({
      "POST sales/imports/": () => json({ id: 4 }, 201),
      "POST sales/lines/match/": () => json({ lines: 3 }),
    });
    await salesApi.upload(1, 2, new File(["a;b\n"], "export.csv", { type: "text/csv" }));
    const form = calls[0]!.body as FormData;
    expect(form.get("profile_id")).toBe("2");
    expect((form.get("file") as File).name).toBe("export.csv");
    await salesApi.match(1, "4780000000999", 5);
    expect(calls[1]!.body).toEqual({ code: "4780000000999", product_id: 5 });
  });
});

describe("LinesPage", () => {
  it("shows a line above the legal price with its cap, in packs and parts, and its cost for finance.view", async () => {
    stub({
      "GET sales/options/": () => json(options()),
      "GET sales/lines/": () => json(page([line()])),
    });
    const app = await testApp("/c/1/sales/lines");
    mountWithProviders(LinesPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    const text = document.body.textContent ?? "";
    expect(text).toContain("Amoksitsillin 500 mg kapsula №16");
    expect(text).toContain("R-778");
    expect(text).toContain("1 pack 1 part");
    expect(text).toContain(en["sales.lines.col.cost"]);
    expect(document.querySelector(".text-danger")?.textContent).toContain("13");
  });

  it("has no cost column without finance.view and sends the cap filter", async () => {
    const calls = stub({
      "GET sales/options/": () => json(options()),
      "GET sales/lines/": () => json(page([line({ cost: undefined })])),
    });
    const app = await testApp("/c/1/sales/lines?cap=true&rx=true");
    as(["dashboard.access", "sales.view"]);
    mountWithProviders(LinesPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    const headers = [...document.querySelectorAll("th")].map((th) => th.textContent?.trim());
    expect(headers).not.toContain(en["sales.lines.col.cost"]);
    const request = new URL(calls.find((call) => call.url.includes("sales/lines/"))!.url, "http://x");
    expect(request.searchParams.get("cap")).toBe("true");
    expect(request.searchParams.get("rx")).toBe("true");
  });
});

describe("ImportPage", () => {
  const imports: SalesImport[] = [
    {
      id: 4,
      profile: { id: 2, name: "Apteka Pro" },
      status: "ready",
      error: "",
      rows: 12,
      receipts: 9,
      lines: 12,
      matched: 10,
      unmatched: 2,
      duplicates: 0,
      unreadable: 0,
      breaches: 1,
      problems: [],
      day_check: [],
      first_day: "2026-10-21",
      last_day: "2026-10-21",
      created_at: "2026-10-22T04:00:00Z",
      started_at: null,
      finished_at: null,
      created_by: null,
    },
  ];

  it("says how to turn imports on when sale lines don't come from imports", async () => {
    stub({ "GET sales/options/": () => json(options("none")), "GET sales/import-profiles/": () => json([]) });
    const app = await testApp("/c/1/sales/import");
    mountWithProviders(ImportPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    expect(document.body.textContent).toContain(en["sales.import.offTitle"]);
    expect(document.body.textContent).toContain(en["sales.import.offAction"]);
  });

  it("lists the files with what waits for a match", async () => {
    stub({
      "GET sales/options/": () => json(options()),
      "GET sales/import-profiles/": () => json([{ id: 2, name: "Apteka Pro", file_kind: "csv", encoding: "", delimiter: "", header_row: 1, columns: { receipt: "Чек" }, date_format: "", default_unit: "pack", branch: { id: 1, name: "Chilonzor", code: "CHL" }, branch_map: {}, is_active: true, created_at: "2026-10-01T00:00:00Z", last_import: null }]),
      "GET sales/imports/": () => json(page(imports)),
    });
    const app = await testApp("/c/1/sales/import");
    mountWithProviders(ImportPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    const text = document.body.textContent ?? "";
    expect(text).toContain("Apteka Pro");
    expect(text).toContain(en["sales.import.status.ready"]);
  });

  it("matches a waiting code to a medicine found through the sales API", async () => {
    const codes: LineCode[] = [{ code: "4780000000999", name: "Ibuprofen 200 mg №10", lines: 2, total: "18000.00", first_day: "2026-10-21", last_day: "2026-10-21", branches: ["Chilonzor"] }];
    const calls = stub({
      "GET sales/options/": () => json(options()),
      "GET sales/import-profiles/": () => json([]),
      "GET sales/lines/codes/": () => json({ results: codes }),
      "GET sales/products/": () => json({ results: [{ id: 5, name: "Ibuprofen 200 mg tabletka №10", trade_name: "", inn: "ibuprofen", barcode: "", rx_required: false, sale_price: "9000.00" }] }),
      "POST sales/lines/match/": () => json({ lines: 2 }),
    });
    const app = await testApp("/c/1/sales/import?tab=match");
    mountWithProviders(ImportPage, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    expect(document.body.textContent).toContain("Ibuprofen 200 mg №10");
    expect(document.body.textContent).toContain("2 lines");
    const button = [...document.querySelectorAll("button")].find((b) => b.textContent?.trim() === en["sales.match.match"]);
    button!.click();
    await flushPromises();
    expect(document.body.textContent).toContain(en["sales.match.confirm"]);
    // The catalogue lookup goes through the sales API.
    const found = await salesApi.products(1, "ibu");
    expect(found.results[0]!.name).toContain("Ibuprofen");
    expect(calls.some((call) => call.url.includes("sales/products/"))).toBe(true);
  });
});

describe("PosCashiersPanel", () => {
  it("links a cash-register code to a person", async () => {
    const calls = stub({
      "GET sales/options/": () => json(options()),
      "GET sales/pos-cashiers/": () => json([{ id: 3, code: "K07", member: null, receipts: 41, last_sold_at: "2026-10-21T15:00:00Z" }]),
      "PATCH sales/pos-cashiers/3/": () => json({ id: 3, code: "K07", member: { id: 16, name: "Madina Saidova" }, receipts: 41, last_sold_at: null }),
    });
    const app = await testApp("/c/1/settings/pos-cashiers");
    mountWithProviders(PosCashiersPanel, { plugins: app.plugins });
    await flushPromises();
    await flushPromises();
    expect(document.body.textContent).toContain("K07");
    expect(document.body.textContent).toContain("41 receipts");
    await salesApi.mapCashier(1, 3, 16);
    expect(calls.find((call) => call.method === "PATCH")!.body).toEqual({ member_id: 16 });
  });
});
