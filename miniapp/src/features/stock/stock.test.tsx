/**
 * The pharmacist's stock screens (PLAN-OWNER §14.17): packs and parts, typed lookup by name, INN
 * and barcode rendering the API's rows, the product with its batches and analogs (with the
 * required title), defektura, the Home card and the shelf-check task's way in, and camera
 * scanning only where `getSupportedFormats()` lists EAN-13 (a fake detector stands in).
 */
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api/client";
import { featureTranslator } from "../../i18n/feature";
import { formatMoney } from "../../lib/money";
import { resolveScreen } from "../../state/deeplink";
import { makeTask, membership, navigationState, person, renderApp } from "../../test/harness";
import { features, featureVisible, findFeature, homeSlots, meItemsByGroup, plusActions, taskSlots } from "../registry";
import type { AppBatch, LookupRow, ProductDetail, StockSettings } from "./api";
import { cleanPhone, expiryGroup, expirySteps, isEan13, isShelfCheckTask, lastDayOfMonth, looksLikeBarcode, packDate, qtyText, sortAnalogs, splitParts } from "./lib";
import { messages } from "./messages";
import ProductPage from "./ProductPage";
import { pickCode, resetScanSupport, supportedFormats } from "./scan";
import { ExpiryCard, ShelfCheckBlock, needsLook } from "./slots";
import StockPage from "./StockPage";

const server = vi.hoisted(() => ({
  calls: [] as { path: string; method: string; body: unknown }[],
  handler: (() => undefined) as (path: string, method: string, body: unknown) => unknown,
}));

vi.mock("../../api/client", async (importOriginal) => {
  const real = await importOriginal<typeof import("../../api/client")>();
  const answer = async (path: string, method: string, body: unknown) => {
    server.calls.push({ path, method, body });
    const result = await server.handler(path, method, body);
    if (result instanceof Error) throw result;
    return result ?? {};
  };
  return {
    ...real,
    api: vi.fn((path: string, options: { method?: string; json?: unknown } = {}) => answer(path, options.method ?? (options.json ? "POST" : "GET"), options.json)),
    apiForm: vi.fn((path: string, fields: unknown, options: { method?: string } = {}) => answer(path, options.method ?? "POST", fields)),
  };
});
vi.mock("../../lib/image", () => ({ downscale: (file: File) => Promise.resolve(file) }));

const stock = findFeature(features, "stock")!;
const company = { id: 1, name: "Demo Dorixona", timezone: "Asia/Tashkent", features: ["stock", "sales"], base_currency: "UZS" };
const nigora = membership({
  company,
  first_name: "Nigora",
  last_name: "Karimova",
  permissions: ["stock.operate", "sales.operate"],
  home_branch: { id: 1, name: "Chilonzor" },
  branch_ids: [1],
} as never);
const reader = membership({ company, permissions: ["sales.view"] } as never);
const me = person([nigora]);
const member = { ...nigora, timeZone: "Asia/Tashkent", companyId: 1 };
const en = featureTranslator(messages, "en");
const uz = featureTranslator(messages, "uz");
const ru = featureTranslator(messages, "ru");
/** Amounts as the screens print them, with the narrow spaces made plain. */
const plain = (text: string | null | undefined) => (text ?? "").replace(/[  ]/g, " ");
const money = (amount: string) => plain(formatMoney(amount, "UZS", "en"));

const BARCODE = "4780000000014";
const SETTINGS: StockSettings = { camera_scanning: true, show_other_branches: true, rx_log: true, fefo_strict: true };

function row(over: Partial<LookupRow> = {}): LookupRow {
  return {
    id: 41,
    name: "Amoksitsillin 500 mg kapsula №16",
    trade_name: "Amoksil-Farm",
    inn: "amoxicillin",
    barcode: BARCODE,
    rx_required: true,
    control_class: "none",
    storage: "room",
    units_per_pack: 2,
    part_label: "blister",
    sale_price: "24000.00",
    part_price: "12000.00",
    quantity: "7.000",
    elsewhere: [{ branch_id: 2, branch: "Yunusobod", quantity: "10.000" }],
    ...over,
  };
}

function batch(over: Partial<AppBatch> = {}): AppBatch {
  return {
    id: 301,
    batch_id: 77,
    branch_id: 1,
    branch: "Chilonzor",
    series: "230415",
    expires_on: "2027-03-31",
    days_left: 120,
    expired: false,
    status: "sellable",
    quantity: "7.000",
    retail_price: "24000.00",
    part_price: "12000.00",
    ...over,
  };
}

function detail(over: Partial<ProductDetail> = {}): ProductDetail {
  return {
    product: row(),
    batches: [batch(), batch({ id: 302, batch_id: 78, series: "230901", expires_on: "2026-11-30", days_left: 23, quantity: "1.000" })],
    analogs: [
      { id: 50, name: "Amoksitsillin 500 mg kapsula №20", trade_name: "Oqtosh-Amoks", inn: "amoxicillin", dosage_form: "capsule", strength: "500 mg", manufacturer: "Oqtosh Farm", rx_required: true, sale_price: "28000.00", quantity: "0.000" },
      { id: 51, name: "Amoksitsillin 500 mg kapsula №16 (Tolzor)", trade_name: "Tolzor-Amoks", inn: "amoxicillin", dosage_form: "capsule", strength: "500 mg", manufacturer: "Tolzor", rx_required: true, sale_price: "21000.00", quantity: "4.000" },
    ],
    ...over,
  };
}

type Handler = (path: string, method: string, body: unknown) => unknown;

/** The stock endpoints as an ordinary day answers them; a test passes what it is about. */
function serve(extra: Handler = () => undefined) {
  server.handler = (path, method, body) => {
    const own = extra(path, method, body);
    if (own !== undefined) return own;
    if (path.endsWith("/stock/settings/")) return SETTINGS;
    if (path.includes("/stock/lookup/")) {
      const q = new URLSearchParams(path.split("?")[1]).get("q") ?? "";
      const known = row();
      const hit = [known.name, known.inn, known.barcode].some((text) => text.toLowerCase().includes(q.toLowerCase()));
      return hit ? [known] : [];
    }
    if (path.endsWith("/stock/products/41/")) return detail();
    if (path.includes("/stock/expiry/")) return [];
    return {};
  };
}

const lookups = () => server.calls.filter((call) => call.path.includes("/stock/lookup/")).map((call) => new URLSearchParams(call.path.split("?")[1]).get("q"));

beforeEach(() => {
  server.calls = [];
  serve();
  resetScanSupport();
  localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  delete (globalThis as Record<string, unknown>).BarcodeDetector;
  delete (navigator as unknown as Record<string, unknown>).mediaDevices;
});

describe("packs and parts", () => {
  it("reads as the counter says it: packs and the loose parts", () => {
    expect(qtyText("7.000", 2, "blister", uz)).toBe("3 qadoq 1 blister");
    expect(qtyText("7.000", 2, "blister", en)).toBe("3 packs 1 blister");
    expect(qtyText("6", 2, "blister", en)).toBe("3 packs");
    expect(qtyText("1", 10, "ampula", uz)).toBe("1 ampula");
    expect(qtyText("1", 1, "", en)).toBe("1 pack");
    expect(qtyText("5", 1, "", ru)).toBe("5 упаковок");
    expect(qtyText("22", 10, "", ru)).toBe("2 упаковки 2 части");
    expect(qtyText("0", 2, "blister", en)).toBe("0 packs");
    expect(qtyText("-3", 1, "", en)).toBe("−3 packs");
    expect(splitParts("25", 10)).toEqual({ packs: 2, parts: 5, negative: false });
  });

  it("groups expiry by the company's steps, expired first", () => {
    expect(expirySteps(undefined)).toEqual([30, 60, 90]);
    expect(expirySteps({ expiry_steps: [120, 14, 60, 60] })).toEqual([14, 60, 120]);
    const steps = [30, 60, 90];
    expect([-1, 0, 30, 31, 60, 90, 91].map((days) => expiryGroup(days, steps))).toEqual(["expired", "30", "30", "60", "60", "90", null]);
  });

  it("writes days as the pack prints them and knows a month's last day", () => {
    expect(packDate("2026-12-31")).toBe("31.12.2026");
    expect(lastDayOfMonth(2027, 2)).toBe("2027-02-28");
    expect(lastDayOfMonth(2028, 2)).toBe("2028-02-29");
    expect(lastDayOfMonth(2026, 12)).toBe("2026-12-31");
  });

  it("checks a barcode's check digit", () => {
    expect(isEan13(BARCODE)).toBe(true);
    expect(isEan13("4780000000015")).toBe(false);
    expect(looksLikeBarcode(" 4780000000014 ")).toBe(true);
    expect(looksLikeBarcode("amox")).toBe(false);
    expect(cleanPhone("+998 (90) 123-45-67")).toBe("+998901234567");
  });

  it("lists analogs I have first, without advice", () => {
    expect(sortAnalogs(detail().analogs).map((analog) => analog.id)).toEqual([51, 50]);
    expect(en("product.analogs")).toBe("Same active ingredient, form and strength");
    expect(uz("product.analogs")).toBe("Ta’sir etuvchi moddasi, shakli va dozasi bir xil");
    expect(ru("product.analogs")).toBe("То же МНН, форма и дозировка");
    for (const dictionary of [messages.en, messages.ru, messages.uz]) {
      expect(Object.values(dictionary).join(" ")).not.toMatch(/recommend|tavsiya|рекоменд/i);
    }
  });
});

describe("the feature", () => {
  const context = (who = nigora) => ({ member: { ...who, timeZone: "Asia/Tashkent", companyId: 1 }, summary: undefined });

  it("shows with the stock module on, to people who may read stock", () => {
    expect(featureVisible(stock, context())).toBe(true);
    expect(featureVisible(stock, context(reader))).toBe(true);
    expect(featureVisible(stock, context(membership({ company, permissions: ["tasks.view"] } as never)))).toBe(false);
    expect(featureVisible(stock, context(membership({ company: { ...company, features: ["sales"] }, permissions: ["stock.operate"] } as never)))).toBe(false);
  });

  it("puts Stock in Me, Defektura in (+), and the Home card only for those who work with stock", () => {
    expect(meItemsByGroup(features, context()).work.map(({ item }) => item.label)).toContain("me.stock");
    expect(plusActions(features, context()).some(({ feature, item }) => feature.id === "stock" && item.id === "defektura")).toBe(true);
    expect(plusActions(features, context(reader)).some(({ feature }) => feature.id === "stock")).toBe(false);
    expect(homeSlots(features, "home.cards", context()).some(({ feature, item }) => feature.id === "stock" && item.id === "expiry")).toBe(true);
    expect(homeSlots(features, "home.cards", context(reader)).some(({ feature }) => feature.id === "stock")).toBe(false);
    expect(taskSlots(features, context()).some(({ feature }) => feature.id === "stock")).toBe(true);
  });

  it("answers the notices' links", () => {
    expect(resolveScreen({ name: "stock.expiry", arg: null }, features)).toEqual({ tab: "home", stack: [{ feature: "stock", page: "expiry", params: {} }] });
    expect(resolveScreen({ name: "stock", arg: null }, features)).toEqual({ tab: "home", stack: [{ feature: "stock", page: "home", params: {} }] });
    expect(resolveScreen({ name: "stock.product", arg: "41" }, features)).toEqual({ tab: "home", stack: [{ feature: "stock", page: "product", params: { id: 41 } }] });
  });

  it("has every text in the three languages", () => {
    const keys = Object.keys(messages.en)
      .map((key) => key.replace(/_(one|few|many|other)$/, ""))
      .sort();
    const base = (dictionary: Record<string, string>) => [...new Set(Object.keys(dictionary).map((key) => key.replace(/_(one|few|many|other)$/, "")))].sort();
    expect(base(messages.ru)).toEqual([...new Set(keys)]);
    expect(base(messages.uz)).toEqual([...new Set(keys)]);
    expect(Object.values(messages.uz).join(" ")).not.toMatch(/['`]/);
  });
});

describe("stock lookup", () => {
  it("finds by name, INN and barcode, and shows what the counter needs", async () => {
    renderApp(<StockPage />, { me });
    const search = screen.getByRole("searchbox", { name: "Search the catalogue" });

    fireEvent.change(search, { target: { value: "amox" } });
    const found = await screen.findByTestId("stock-row");
    const text = plain(found.textContent);
    expect(text).toContain("Amoksitsillin 500 mg kapsula №16");
    expect(text).toContain("Amoksil-Farm · amoxicillin");
    expect(text).toContain(money("24000.00"));
    expect(text).toContain(`${money("12000.00")} per blister`);
    expect(text).toContain("Here: 3 packs 1 blister");
    expect(text).toContain("Elsewhere: Yunusobod 5 packs");
    expect(within(found).getByText("Prescription")).toBeTruthy();

    fireEvent.change(search, { target: { value: "amoxicillin" } });
    await waitFor(() => expect(lookups()).toContain("amoxicillin"));
    fireEvent.change(search, { target: { value: BARCODE } });
    await waitFor(() => expect(lookups()).toContain(BARCODE));
    expect(await screen.findByText("Amoksitsillin 500 mg kapsula №16")).toBeTruthy();

    fireEvent.click(screen.getByTestId("stock-row"));
    expect(navigationState().stack.at(-1)).toEqual({ feature: "stock", page: "product", params: { id: 41 } });
  });

  it("waits for two letters, then says when nothing matches and offers defektura", async () => {
    renderApp(<StockPage />, { me });
    const search = screen.getByRole("searchbox", { name: "Search the catalogue" });
    fireEvent.change(search, { target: { value: "a" } });
    expect(screen.getByText("Expiry check")).toBeTruthy();
    fireEvent.change(search, { target: { value: "Ibuprofen sirop" } });
    expect(await screen.findByText("Nothing found")).toBeTruthy();
    expect(lookups()).not.toContain("a");
    fireEvent.click(screen.getByRole("button", { name: "Defektura" }));
    expect(navigationState().sheet).toEqual({ kind: "feature", feature: "stock", sheet: "defektura", params: { name: "Ibuprofen sirop" } });
  });

  it("marks what isn't here and what keeps no stock", async () => {
    serve((path) => (path.includes("/stock/lookup/") ? [row({ quantity: "0.000", elsewhere: [] }), row({ id: 42, name: "Bint 7×14", quantity: null, rx_required: false, units_per_pack: 1 })] : undefined));
    renderApp(<StockPage />, { me });
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "bi" } });
    const rows = await screen.findAllByTestId("stock-row");
    expect(plain(rows[0].textContent)).toContain("None here");
    expect(plain(rows[1].textContent)).toContain("Stock not kept");
    expect(plain(rows[1].textContent)).not.toContain("per");
  });
});

describe("the product", () => {
  it("shows the prices, the batches here, the other pharmacies and the analogs under their title", async () => {
    renderApp(<ProductPage params={{ id: 41 }} />, { me });
    expect(await screen.findByRole("heading", { name: "Amoksitsillin 500 mg kapsula №16" })).toBeTruthy();
    const page = plain(document.body.textContent);
    expect(page).toContain(money("24000.00"));
    expect(page).toContain("Price per blister");
    expect(page).toContain("Here: 3 packs 1 blister");
    expect(page).toContain("Series 230415");
    expect(page).toContain("expires 30.11.2026 · 23 days left");
    expect(page).toContain("At other pharmacies");
    expect(page).toContain("Yunusobod");
    const analogs = screen.getByRole("region", { name: "Same active ingredient, form and strength" });
    const names = within(analogs)
      .getAllByRole("button")
      .map((button) => button.textContent ?? "");
    expect(names[0]).toContain("Tolzor");
    expect(names[0]).toContain("In stock here");
    expect(names[1]).toContain("None here");
    fireEvent.click(await screen.findByRole("button", { name: "Record a prescription" }));
    expect(navigationState().stack.at(-1)).toEqual({ feature: "stock", page: "rx", params: { product: 41 } });
  });

  it("offers defektura when there is none here", async () => {
    serve((path) => (path.endsWith("/stock/products/41/") ? detail({ product: row({ quantity: "0.000" }), batches: [] }) : undefined));
    renderApp(<ProductPage params={{ id: 41 }} />, { me });
    fireEvent.click(await screen.findByRole("button", { name: "Defektura" }));
    expect(navigationState().sheet).toEqual({ kind: "feature", feature: "stock", sheet: "defektura", params: { product: 41, name: "Amoksitsillin 500 mg kapsula №16" } });
  });

  it("gives a reader no buttons that change anything", async () => {
    serve((path) => (path.endsWith("/stock/products/41/") ? detail({ product: row({ quantity: "0.000" }), batches: [] }) : undefined));
    renderApp(<ProductPage params={{ id: 41 }} />, { me: person([reader]) });
    expect(await screen.findByText("None here")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Defektura" })).toBeNull();
  });
});

describe("defektura", () => {
  it("sends a catalogue item or the name as asked, the packs and the phone", async () => {
    serve((path, method) => (path.endsWith("/stock/defektura/") && method === "POST" ? { id: 9 } : undefined));
    renderApp(<StockPage />, { me, init: { sheet: { kind: "feature", feature: "stock", sheet: "defektura", params: {} } } });
    const name = await screen.findByPlaceholderText("As the customer asked for it");
    fireEvent.change(name, { target: { value: "Ibuprofen 200 mg" } });
    fireEvent.click(screen.getByRole("button", { name: "More" }));
    fireEvent.change(screen.getByPlaceholderText("+998 90 123 45 67"), { target: { value: "+998 90 123 45 67" } });
    fireEvent.click(screen.getByRole("button", { name: "Add to defektura" }));
    await waitFor(() => expect(server.calls.some((call) => call.path.endsWith("/stock/defektura/"))).toBe(true));
    const sent = server.calls.find((call) => call.path.endsWith("/stock/defektura/"))!;
    expect(sent.body).toEqual({ product: null, name: "Ibuprofen 200 mg", packs: "2", customer_phone: "+998901234567" });
    expect(await screen.findByText("Added to defektura")).toBeTruthy();
  });

  it("takes a product picked from the catalogue", async () => {
    serve((path, method) => (path.endsWith("/stock/defektura/") && method === "POST" ? { id: 9 } : undefined));
    renderApp(<StockPage />, { me, init: { sheet: { kind: "feature", feature: "stock", sheet: "defektura", params: { product: 41, name: "Amoksitsillin 500 mg kapsula №16" } } } });
    fireEvent.click(await screen.findByRole("button", { name: "Add to defektura" }));
    await waitFor(() => expect(server.calls.some((call) => call.path.endsWith("/stock/defektura/"))).toBe(true));
    expect(server.calls.find((call) => call.path.endsWith("/stock/defektura/"))!.body).toEqual({ product: 41, name: "", packs: "1", customer_phone: "" });
  });

  it("keeps the form when the server refuses", async () => {
    serve((path) => (path.endsWith("/stock/defektura/") ? new ApiError(400, { detail: "You don't work at any pharmacy yet." }) : undefined));
    renderApp(<StockPage />, { me, init: { sheet: { kind: "feature", feature: "stock", sheet: "defektura", params: { name: "Validol" } } } });
    fireEvent.click(await screen.findByRole("button", { name: "Add to defektura" }));
    expect(await screen.findByText("You don't work at any pharmacy yet.")).toBeTruthy();
    expect((screen.getByPlaceholderText("As the customer asked for it") as HTMLInputElement).value).toBe("Validol");
  });
});

describe("Home and the task screen", () => {
  const expiring = [
    batch({ id: 1, days_left: -3, expired: true, expires_on: "2026-11-04" }),
    batch({ id: 2, days_left: -1, expired: true }),
    batch({ id: 3, days_left: 12 }),
  ];

  it("counts what still needs a look, leaving out what this phone already marked", () => {
    expect(needsLook(expiring, {}).expired.map((item) => item.id)).toEqual([1, 2]);
    expect(needsLook(expiring, { 1: { writeoff: 5 }, 3: { shelf: "2026-11-07" } })).toEqual({ expired: [expiring[1]], soon: [] });
  });

  it("puts the expired batches first, then what expires within the first step", async () => {
    serve((path) => (path.includes("/stock/expiry/") ? expiring : undefined));
    const { unmount } = renderApp(<ExpiryCard member={member} summary={undefined} />, { me });
    expect(await screen.findByText("2 expired batches are still here")).toBeTruthy();
    expect(screen.getByText("Chilonzor: propose a write-off")).toBeTruthy();
    expect(server.calls.some((call) => call.path.endsWith("/stock/expiry/?within=30"))).toBe(true);
    fireEvent.click(screen.getByRole("button"));
    expect(navigationState().stack.at(-1)).toEqual({ feature: "stock", page: "expiry", params: undefined });
    unmount();

    serve((path) => (path.includes("/stock/expiry/") ? [batch({ id: 3, days_left: 12 })] : undefined));
    renderApp(<ExpiryCard member={member} summary={undefined} />, { me });
    expect(await screen.findByText("1 batch expires within 30 days here")).toBeTruthy();
  });

  it("opens the expiry check from the monthly shelf check task only", () => {
    const shelf = makeTask({ title: "Expiry shelf check: Chilonzor", created_by: null });
    expect(isShelfCheckTask(shelf)).toBe(true);
    expect(isShelfCheckTask({ title: "Проверка сроков годности: Юнусабад", created_by: null })).toBe(true);
    expect(isShelfCheckTask({ title: "Yaroqlilik muddatini tekshirish: Chilonzor", created_by: null })).toBe(true);
    expect(isShelfCheckTask(makeTask({ title: "Expiry shelf check: Chilonzor" }))).toBe(false);
    expect(isShelfCheckTask(makeTask({ title: "Count the till", created_by: null }))).toBe(false);

    renderApp(<ShelfCheckBlock member={member} summary={undefined} task={shelf} />, { me });
    fireEvent.click(screen.getByRole("button", { name: "Open the expiry check" }));
    expect(navigationState().stack.at(-1)).toEqual({ feature: "stock", page: "expiry", params: undefined });
    cleanup();
    const { container } = renderApp(<ShelfCheckBlock member={member} summary={undefined} task={makeTask()} />, { me });
    expect(container.querySelector(".stk-task-card")).toBeNull();
  });
});

describe("camera scanning", () => {
  class FakeDetector {
    static formats = ["qr_code", "ean_13", "code_128"];
    static made: string[][] = [];
    static async getSupportedFormats() {
      return FakeDetector.formats;
    }
    constructor(options: { formats: string[] }) {
      FakeDetector.made.push(options.formats);
    }
    async detect() {
      return [
        { rawValue: "4780000000015", format: "ean_13" },
        { rawValue: BARCODE, format: "ean_13" },
      ];
    }
  }
  const track = { stop: vi.fn() };
  const camera = () =>
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: vi.fn(async () => ({ getTracks: () => [track] })) } });

  beforeEach(() => {
    FakeDetector.formats = ["qr_code", "ean_13", "code_128"];
    FakeDetector.made = [];
    track.stop.mockClear();
  });

  it("is offered only where the detector lists EAN-13 and a camera exists", async () => {
    expect(await supportedFormats({})).toBeNull();
    expect(await supportedFormats({ BarcodeDetector: FakeDetector })).toBeNull();
    const withCamera = { BarcodeDetector: FakeDetector, navigator: { mediaDevices: { getUserMedia: () => undefined } } as unknown as Navigator };
    expect(await supportedFormats(withCamera)).toEqual(["ean_13"]);
    FakeDetector.formats = ["qr_code", "code_128"];
    expect(await supportedFormats(withCamera)).toBeNull();
  });

  it("picks an EAN-13 with a right check digit", () => {
    expect(pickCode([{ rawValue: "4780000000015", format: "ean_13" }])).toBeNull();
    expect(pickCode([{ rawValue: BARCODE, format: "ean_13" }])).toBe(BARCODE);
    expect(pickCode([{ rawValue: "https://t.me/x", format: "qr_code" }])).toBeNull();
    expect(pickCode([{ rawValue: "12345670", format: "ean_8" }])).toBe("12345670");
  });

  it("shows no scan button without the detector, or while the company keeps scanning off", async () => {
    renderApp(<StockPage />, { me });
    await waitFor(() => expect(server.calls.some((call) => call.path.endsWith("/stock/settings/"))).toBe(true));
    expect(screen.queryByRole("button", { name: "Scan a barcode" })).toBeNull();
    cleanup();

    (globalThis as Record<string, unknown>).BarcodeDetector = FakeDetector;
    camera();
    resetScanSupport();
    serve((path) => (path.endsWith("/stock/settings/") ? { ...SETTINGS, camera_scanning: false } : undefined));
    renderApp(<StockPage />, { me });
    await waitFor(() => expect(server.calls.some((call) => call.path.endsWith("/stock/settings/"))).toBe(true));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByRole("button", { name: "Scan a barcode" })).toBeNull();
    // Typed search still works.
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "amox" } });
    expect(await screen.findByTestId("stock-row")).toBeTruthy();
  });

  it("reads a pack and opens its item when exactly one matches", async () => {
    (globalThis as Record<string, unknown>).BarcodeDetector = FakeDetector;
    camera();
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
    renderApp(<StockPage />, { me });
    fireEvent.click(await screen.findByRole("button", { name: "Scan a barcode" }));
    await waitFor(() => expect(navigationState().stack.at(-1)).toEqual({ feature: "stock", page: "product", params: { id: 41 } }));
    expect(FakeDetector.made).toEqual([["ean_13"]]);
    expect(lookups()).toContain(BARCODE);
    expect(navigationState().sheet).toBeNull();
    expect(track.stop).toHaveBeenCalled();
    expect((screen.getByRole("searchbox") as HTMLInputElement).value).toBe(BARCODE);
  });

  it("says when the camera is refused and leaves typing", async () => {
    (globalThis as Record<string, unknown>).BarcodeDetector = FakeDetector;
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: vi.fn(async () => Promise.reject(Object.assign(new Error("no"), { name: "NotAllowedError" }))) },
    });
    renderApp(<StockPage />, { me });
    fireEvent.click(await screen.findByRole("button", { name: "Scan a barcode" }));
    expect(await screen.findByText("The camera isn’t allowed. Type the code instead.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Type the code" }));
    await waitFor(() => expect(navigationState().sheet).toBeNull());
  });
});
