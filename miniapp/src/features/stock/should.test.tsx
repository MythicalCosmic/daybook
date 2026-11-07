/**
 * The Should screens of PLAN-OWNER §14.17: transfers in ("Incoming from Yunusobod: 2 items" →
 * count what arrived → receive), the blind count (the expected quantity never reaches the
 * screen), receiving with the server's warnings, and the prescription entry.
 */
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api/client";
import { resolveScreen } from "../../state/deeplink";
import { membership, navigationState, person, renderApp } from "../../test/harness";
import { features } from "../registry";
import { blind, type Count, type IncomingTransfer, type Receipt } from "./api";
import CountPage from "./CountPage";
import CountsPage from "./CountsPage";
import ReceivePage from "./ReceivePage";
import RxPage from "./RxPage";
import { IncomingCard } from "./slots";
import TransferPage from "./TransferPage";
import TransfersPage from "./TransfersPage";

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

const company = { id: 1, name: "Demo Dorixona", timezone: "Asia/Tashkent", features: ["stock"], base_currency: "UZS" };
const nigora = membership({ company, permissions: ["stock.operate"], home_branch: { id: 1, name: "Chilonzor" }, branch_ids: [1] } as never);
const me = person([nigora]);
const member = { ...nigora, timeZone: "Asia/Tashkent", companyId: 1 };
const calls = (end: string, method = "POST") => server.calls.filter((call) => call.path.endsWith(end) && call.method === method);

function incoming(over: Partial<IncomingTransfer["transfer"]> = {}): IncomingTransfer {
  return {
    transfer: {
      id: 7,
      number: "TR-0007",
      status: "sent",
      from_branch: { id: 2, name: "Yunusobod", code: "YNS" },
      to_branch: { id: 1, name: "Chilonzor", code: "CHL" },
      note: "",
      lines_count: 2,
      created_at: "2026-11-06T09:00:00+05:00",
      sent_at: "2026-11-06T09:30:00+05:00",
      sent_by: { id: 3, name: "Madina Yusupova", photo_url: null },
      received_at: null,
      received_by: null,
      resolution: "",
      resolved_at: null,
      void_reason: "",
      ...over,
    },
    lines: [
      { id: 71, product: { id: 41, name: "Amoksitsillin 500 mg kapsula №16" }, units_per_pack: 2, batch_id: 77, series: "230415", expires_on: "2027-03-31", quantity_sent: "6.000", quantity_received: null },
      { id: 72, product: { id: 42, name: "Paratsetamol 500 mg tabletka №20" }, units_per_pack: 1, batch_id: 78, series: "PX-11", expires_on: "2027-01-31", quantity_sent: "3.000", quantity_received: null },
    ],
  };
}

type Handler = (path: string, method: string, body: unknown) => unknown;

function serve(extra: Handler = () => undefined) {
  server.handler = (path, method, body) => {
    const own = extra(path, method, body);
    if (own !== undefined) return own;
    if (path.endsWith("/stock/settings/")) return { camera_scanning: false, show_other_branches: true, rx_log: true, fefo_strict: true };
    if (path.endsWith("/stock/transfers/incoming/")) return [incoming()];
    return undefined;
  };
}

beforeEach(() => {
  server.calls = [];
  localStorage.clear();
  serve();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  delete (URL as unknown as Record<string, unknown>).createObjectURL;
  delete (URL as unknown as Record<string, unknown>).revokeObjectURL;
});

describe("transfers in", () => {
  it("lists what other pharmacies sent here and opens one to count", async () => {
    renderApp(<TransfersPage />, { me });
    const row = await screen.findByRole("button", { name: /From Yunusobod/ });
    expect(row.textContent).toContain("TR-0007 · 2 items · sent");
    fireEvent.click(row);
    expect(navigationState().stack.at(-1)).toEqual({ feature: "stock", page: "transfer", params: { id: 7 } });
  });

  it("says when nothing is on the way", async () => {
    serve((path) => (path.endsWith("/stock/transfers/incoming/") ? [] : undefined));
    renderApp(<TransfersPage />, { me });
    expect(await screen.findByText("Nothing on the way")).toBeTruthy();
  });

  it("puts each transfer on Home", async () => {
    renderApp(<IncomingCard member={member} summary={undefined} />, { me });
    expect(await screen.findByText("Incoming from Yunusobod")).toBeTruthy();
    expect(screen.getByText("2 items: count what arrived")).toBeTruthy();
    fireEvent.click(screen.getByRole("button"));
    expect(navigationState().stack.at(-1)).toEqual({ feature: "stock", page: "transfer", params: { id: 7 } });
  });

  it("opens from the notice's link", () => {
    expect(resolveScreen({ name: "stock.transfer", arg: "7" }, features)).toEqual({ tab: "home", stack: [{ feature: "stock", page: "transfer", params: { id: 7 } }] });
  });

  it("receives everything as sent", async () => {
    serve((path, method) => (path.endsWith("/stock/transfers/7/receive/") && method === "POST" ? { ...incoming({ status: "received" }) } : undefined));
    renderApp(<TransferPage params={{ id: 7 }} />, { me, init: { stack: [{ feature: "stock", page: "transfers" }, { feature: "stock", page: "transfer", params: { id: 7 } }] } });
    const lines = await screen.findAllByTestId("transfer-line");
    expect(lines[0].textContent).toContain("Series 230415 · expires 31.03.2027");
    expect(lines[0].textContent).toContain("Sent: 3 packs");
    expect(lines[1].textContent).toContain("Sent: 3 packs");
    fireEvent.click(screen.getByRole("button", { name: "Receive" }));
    await waitFor(() => expect(calls("/stock/transfers/7/receive/")).toHaveLength(1));
    expect(calls("/stock/transfers/7/receive/")[0].body).toEqual({ lines: [{ line: 71, quantity: "6" }, { line: 72, quantity: "3" }] });
    expect(await screen.findByText("Received")).toBeTruthy();
    expect(navigationState().stack).toEqual([{ feature: "stock", page: "transfers" }]);
  });

  it("receives less than sent as a shortage the heads hear about", async () => {
    serve((path, method) => (path.endsWith("/stock/transfers/7/receive/") && method === "POST" ? { ...incoming({ status: "disputed" }) } : undefined));
    renderApp(<TransferPage params={{ id: 7 }} />, { me });
    const lines = await screen.findAllByTestId("transfer-line");
    // One loose blister fewer of the first item: 2 packs 1 blister.
    fireEvent.click(within(lines[0]).getAllByRole("button", { name: "Less" })[0]);
    fireEvent.click(within(lines[0]).getAllByRole("button", { name: "More" })[1]);
    expect(screen.getByText(/Less than sent on 1 line/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Receive with a shortage" }));
    await waitFor(() => expect(calls("/stock/transfers/7/receive/")).toHaveLength(1));
    expect(calls("/stock/transfers/7/receive/")[0].body).toEqual({ lines: [{ line: 71, quantity: "5" }, { line: 72, quantity: "3" }] });
    expect(await screen.findByText("Received with a shortage: the heads hear")).toBeTruthy();
  });

  it("never takes more than was sent", async () => {
    renderApp(<TransferPage params={{ id: 7 }} />, { me });
    const lines = await screen.findAllByTestId("transfer-line");
    expect((within(lines[1]).getAllByRole("button", { name: "More" })[0] as HTMLButtonElement).disabled).toBe(true);
  });

  it("keeps the counts and shows the reason when the server refuses", async () => {
    serve((path) => (path.endsWith("/receive/") ? new ApiError(400, { detail: "This transfer wasn't sent." }) : undefined));
    renderApp(<TransferPage params={{ id: 7 }} />, { me });
    await screen.findAllByTestId("transfer-line");
    fireEvent.click(screen.getByRole("button", { name: "Receive" }));
    expect(await screen.findByText("This transfer wasn't sent.")).toBeTruthy();
    expect(screen.getAllByTestId("transfer-line")).toHaveLength(2);
  });

  it("says when the transfer was received already", async () => {
    serve((path) => (path.endsWith("/stock/transfers/incoming/") ? [] : undefined));
    renderApp(<TransferPage params={{ id: 7 }} />, { me });
    expect(await screen.findByText("Already received")).toBeTruthy();
  });
});

function count(over: Partial<Count> = {}): Count {
  return {
    id: 5,
    kind: "partial",
    status: "open",
    branch: { id: 1, name: "Chilonzor", code: "CHL" },
    lines: [
      { id: 501, product: { id: 41, name: "Amoksitsillin 500 mg kapsula №16" }, units_per_pack: 2, part_label: "blister", batch_id: 77, series: "230415", expires_on: "2027-03-31", counted: null },
      { id: 502, product: { id: 42, name: "Paratsetamol 500 mg tabletka №20" }, units_per_pack: 1, part_label: "", batch_id: 78, series: "PX-11", expires_on: "2027-01-31", counted: "3.000" },
    ],
    ...over,
  };
}

/** What a careless server might add: the counter's screen must never hold it. */
const withExpected = (value: Count) => ({ ...value, lines: value.lines.map((line) => ({ ...line, expected: "9.000", difference: "-1.000" })) });

describe("the blind count", () => {
  it("never keeps the expected quantity", () => {
    const cleaned = blind(withExpected(count()) as Count);
    expect(JSON.stringify(cleaned)).not.toMatch(/expected|difference/);
  });

  it("shows product, series and expiry, and what is left to count", async () => {
    serve((path) => (path.endsWith("/stock/counts/5/lines/") ? withExpected(count()) : undefined));
    const { client } = renderApp(<CountPage params={{ id: 5 }} />, { me });
    const lines = await screen.findAllByTestId("count-line");
    expect(lines).toHaveLength(1);
    expect(lines[0].textContent).toContain("Amoksitsillin 500 mg kapsula №16");
    expect(lines[0].textContent).toContain("Series 230415 · expires 31.03.2027");
    expect(screen.getByText("1 of 2 counted")).toBeTruthy();
    expect(document.body.textContent).not.toContain("9.000");
    expect(JSON.stringify(client.getQueryData(["stock", 1, "count", 5]))).not.toMatch(/expected/);
    fireEvent.click(screen.getByRole("radio", { name: /All/ }));
    expect(screen.getAllByTestId("count-line")[1].textContent).toContain("Counted: 3 packs");
  });

  it("saves a count at once and goes on to the next line", async () => {
    let answer: (value: unknown) => void = () => undefined;
    serve((path, method) => {
      if (path.endsWith("/stock/counts/5/lines/") && method === "GET") return count();
      if (path.endsWith("/stock/counts/5/lines/") && method === "PATCH") return new Promise((resolve) => (answer = resolve));
      return undefined;
    });
    renderApp(<CountPage params={{ id: 5 }} />, { me });
    fireEvent.click(within((await screen.findAllByTestId("count-line"))[0]).getByRole("button", { name: "Count" }));
    const line = screen.getAllByTestId("count-line")[0];
    fireEvent.click(within(line).getAllByRole("button", { name: "More" })[0]);
    fireEvent.click(within(line).getAllByRole("button", { name: "More" })[1]);
    fireEvent.click(within(line).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls("/stock/counts/5/lines/", "PATCH")).toHaveLength(1));
    expect(calls("/stock/counts/5/lines/", "PATCH")[0].body).toEqual({ lines: [{ line: 501, counted: "3" }] });
    // Shown before the server answers: everything is counted now.
    expect(await screen.findByText("2 of 2 counted")).toBeTruthy();
    answer(count({ lines: count().lines.map((row) => ({ ...row, counted: row.counted ?? "3.000" })) }));
    expect(await screen.findByText("Everything is counted. Tell the head.", { selector: ".banner *" })).toBeTruthy();
  });

  it("takes a refused save back", async () => {
    serve((path, method) => {
      if (path.endsWith("/stock/counts/5/lines/") && method === "GET") return count();
      if (method === "PATCH") return new ApiError(400, { detail: "This count is closed." });
      return undefined;
    });
    renderApp(<CountPage params={{ id: 5 }} />, { me });
    fireEvent.click(within((await screen.findAllByTestId("count-line"))[0]).getByRole("button", { name: "Count" }));
    fireEvent.click(within(screen.getAllByTestId("count-line")[0]).getByRole("button", { name: "Save" }));
    expect(await screen.findByText("This count is closed.")).toBeTruthy();
    expect(screen.getByText("1 of 2 counted")).toBeTruthy();
  });

  it("finds a line by a scanned or typed barcode", async () => {
    serve((path) => {
      if (path.endsWith("/stock/counts/5/lines/")) return count({ lines: count().lines.map((row) => ({ ...row, counted: null })) });
      if (path.includes("/stock/lookup/")) return [{ id: 42, name: "Paratsetamol 500 mg tabletka №20" }];
      return undefined;
    });
    renderApp(<CountPage params={{ id: 5 }} />, { me });
    await screen.findAllByTestId("count-line");
    fireEvent.change(screen.getByRole("searchbox", { name: "Find a line" }), { target: { value: "4780000000021" } });
    await waitFor(() => expect(screen.getAllByTestId("count-line")).toHaveLength(1));
    expect(screen.getByTestId("count-line").textContent).toContain("Paratsetamol");
  });

  it("says when the count is closed", async () => {
    serve((path) => (path.endsWith("/stock/counts/5/lines/") ? count({ status: "submitted" }) : undefined));
    renderApp(<CountPage params={{ id: 5 }} />, { me });
    expect(await screen.findByText("This count is closed")).toBeTruthy();
  });

  it("lists the open counts, and copes with a server that can't list them yet", async () => {
    serve((path) => (path.endsWith("/stock/counts/") ? new ApiError(404, null) : undefined));
    renderApp(<CountsPage />, { me });
    expect(await screen.findByText("No count is open")).toBeTruthy();
    cleanup();
    serve((path) =>
      path.endsWith("/stock/counts/")
        ? [{ id: 5, kind: "full", status: "open", branch: { id: 1, name: "Chilonzor", code: "CHL" }, lines_count: 120, counted_count: 30, created_at: "2026-11-07T08:00:00+05:00" }]
        : undefined,
    );
    renderApp(<CountsPage />, { me });
    fireEvent.click(await screen.findByRole("button", { name: /Full count/ }));
    expect(navigationState().stack.at(-1)).toEqual({ feature: "stock", page: "count", params: { id: 5 } });
    expect(resolveScreen({ name: "stock.count", arg: "5" }, features)).toEqual({ tab: "home", stack: [{ feature: "stock", page: "count", params: { id: 5 } }] });
  });
});

function receipt(over: Partial<Receipt> = {}): Receipt {
  return {
    id: 31,
    status: "draft",
    branch: { id: 1, name: "Chilonzor", code: "CHL" },
    supplier: { id: 9, name: "Ko‘kterak Farm Distribyutor" },
    supplier_invoice_number: "N-1180",
    supplier_invoice_date: "2026-11-06",
    lines: [],
    created_at: "2026-11-07T09:00:00+05:00",
    ...over,
  };
}

const LINE = { id: 311, product: { id: 41, name: "Amoksitsillin 500 mg kapsula №16" }, units_per_pack: 2, series: "230415", expires_on: "2027-03-31", packs: "2.000", quantity: "4.000", warnings: ["short_shelf_life", "something_new"] };

describe("receiving", () => {
  it("starts a receipt with the distributor, the nakladnoy's number, date and photo", async () => {
    serve((path, method) => {
      if (path.endsWith("/stock/receipts/") && method === "GET") return [];
      if (path.endsWith("/stock/suppliers/")) return [{ id: 9, name: "Ko‘kterak Farm Distribyutor" }, { id: 10, name: "Oqtosh Med Ta’minot" }];
      if (path.endsWith("/stock/receipts/") && method === "POST") return receipt();
      return undefined;
    });
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: () => "blob:x" });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: () => undefined });
    renderApp(<ReceivePage params={{}} />, { me, init: { stack: [{ feature: "stock", page: "receive" }] } });
    const start = await screen.findByRole("button", { name: "Start the receipt" });
    expect((start as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(await screen.findByRole("combobox", { name: "Distributor" }), { target: { value: "10" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Nakladnoy number" }), { target: { value: "OM-77" } });
    const photo = new File(["jpeg"], "nakladnoy.jpg", { type: "image/jpeg" });
    fireEvent.change(document.querySelector('input[type="file"][capture]') as HTMLInputElement, { target: { files: [photo] } });
    fireEvent.click(start);
    await waitFor(() => expect(calls("/stock/receipts/")).toHaveLength(1));
    const body = calls("/stock/receipts/")[0].body as Record<string, unknown>;
    expect(body).toMatchObject({ supplier: 10, supplier_invoice_number: "OM-77", file: photo });
    expect(body.supplier_invoice_date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    await waitFor(() => expect(navigationState().stack).toEqual([{ feature: "stock", page: "receive", params: { id: 31 } }]));
  });

  it("offers the distributors of recent receipts until the app has a list, and says when there are none", async () => {
    serve((path, method) => {
      if (path.endsWith("/stock/receipts/") && method === "GET") return [receipt({ status: "submitted", lines: [LINE] })];
      if (path.endsWith("/stock/suppliers/")) return new ApiError(404, null);
      return undefined;
    });
    renderApp(<ReceivePage params={{}} />, { me });
    expect(await screen.findByText("Ko‘kterak Farm Distribyutor", { selector: ".row-title" })).toBeTruthy();
    expect(screen.getByText("No. N-1180 of 06.11.2026 · 1 line")).toBeTruthy();
    expect(screen.getByText("Waiting for posting", { selector: ".tag" })).toBeTruthy();
    const select = screen.getByRole("combobox", { name: "Distributor" }) as HTMLSelectElement;
    expect(select.value).toBe("9");
    cleanup();

    serve((path, method) => {
      if (path.endsWith("/stock/receipts/") && method === "GET") return [];
      if (path.endsWith("/stock/suppliers/")) return new ApiError(404, null);
      return undefined;
    });
    renderApp(<ReceivePage params={{}} />, { me });
    expect(await screen.findByText(/No distributor is set up for the app yet/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Start the receipt" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("adds a line with series, the expiry month and year, packs and cost, and shows the server's warnings", async () => {
    serve((path, method) => {
      if (path.endsWith("/stock/receipts/") && method === "GET") return [receipt()];
      if (path.includes("/stock/lookup/")) return [{ id: 41, name: "Amoksitsillin 500 mg kapsula №16", inn: "amoxicillin", barcode: "4780000000014" }];
      if (path.endsWith("/stock/receipts/31/lines/") && method === "POST") return receipt({ lines: [LINE] });
      return undefined;
    });
    renderApp(<ReceivePage params={{ id: 31 }} />, { me });
    const form = await screen.findByTestId("add-line");
    fireEvent.change(within(form).getByRole("searchbox", { name: "Medicine" }), { target: { value: "amox" } });
    fireEvent.click(await within(form).findByRole("button", { name: /Amoksitsillin 500 mg kapsula №16/ }));
    fireEvent.change(within(form).getByRole("textbox", { name: "Series" }), { target: { value: "230415" } });
    fireEvent.change(within(form).getByRole("combobox", { name: "Month" }), { target: { value: "3" } });
    const year = within(form).getByRole("combobox", { name: "Year" }) as HTMLSelectElement;
    fireEvent.change(year, { target: { value: year.options[2].value } });
    fireEvent.click(within(form).getByRole("button", { name: "More" }));
    fireEvent.change(within(form).getByRole("textbox", { name: "Cost per pack" }), { target: { value: "15000" } });
    fireEvent.click(within(form).getByRole("button", { name: "Add to the receipt" }));
    await waitFor(() => expect(calls("/stock/receipts/31/lines/")).toHaveLength(1));
    expect(calls("/stock/receipts/31/lines/")[0].body).toEqual({ product: 41, series: "230415", expires_on: `${year.options[2].value}-03-31`, packs: "2", unit_cost: "15000" });
    const line = await screen.findByTestId("receipt-line");
    expect(line.textContent).toContain("Series 230415 · expires 31.03.2027 · 2 packs");
    expect(within(line).getByText("Short shelf life")).toBeTruthy();
    expect(within(line).getByText("something_new")).toBeTruthy();
    // The form is ready for the next line.
    expect((within(screen.getByTestId("add-line")).getByRole("textbox", { name: "Series" }) as HTMLInputElement).value).toBe("");
  });

  it("sends the receipt for posting", async () => {
    serve((path, method) => {
      if (path.endsWith("/stock/receipts/") && method === "GET") return [receipt({ lines: [LINE] })];
      if (path.endsWith("/stock/receipts/31/submit/") && method === "POST") return receipt({ status: "submitted", lines: [LINE] });
      return undefined;
    });
    renderApp(<ReceivePage params={{ id: 31 }} />, { me });
    fireEvent.click(await screen.findByRole("button", { name: "Send for posting" }));
    expect(await screen.findByText("Sent: the head checks and posts it")).toBeTruthy();
    expect(await screen.findByText("Waiting for posting: the head checks it.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Remove" })).toBeNull();
  });

  it("removes a line while the receipt is a draft", async () => {
    serve((path, method) => {
      if (path.endsWith("/stock/receipts/") && method === "GET") return [receipt({ lines: [LINE] })];
      if (path.endsWith("/stock/receipts/31/lines/311/") && method === "DELETE") return receipt();
      return undefined;
    });
    renderApp(<ReceivePage params={{ id: 31 }} />, { me });
    fireEvent.click(await screen.findByRole("button", { name: "Remove" }));
    await waitFor(() => expect(screen.queryByTestId("receipt-line")).toBeNull());
    expect(calls("/stock/receipts/31/lines/311/", "DELETE")).toHaveLength(1);
  });
});

const RX_PRODUCT = {
  id: 41,
  name: "Amoksitsillin 500 mg kapsula №16",
  trade_name: "",
  inn: "amoxicillin",
  barcode: "",
  rx_required: true,
  control_class: "none",
  storage: "room",
  units_per_pack: 2,
  part_label: "blister",
  sale_price: "24000.00",
  part_price: "12000.00",
  quantity: "7.000",
  elsewhere: [],
};

describe("prescription entry", () => {
  it("is off while the company keeps no prescription log", async () => {
    serve((path) => (path.endsWith("/stock/settings/") ? { camera_scanning: false, show_other_branches: true, rx_log: false, fefo_strict: true } : undefined));
    renderApp(<RxPage params={{}} />, { me });
    expect(await screen.findByText("The prescription log is off")).toBeTruthy();
  });

  it("records a prescription for the item it was opened from, never the patient", async () => {
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: () => "blob:x" });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: () => undefined });
    serve((path, method) => {
      if (path.endsWith("/stock/products/41/")) return { product: RX_PRODUCT, batches: [], analogs: [] };
      if (path.endsWith("/stock/rx/") && method === "POST") return { id: 3, flags: ["no_e_prescription"] };
      return undefined;
    });
    renderApp(<RxPage params={{ product: 41 }} />, { me, init: { stack: [{ feature: "stock", page: "product", params: { id: 41 } }, { feature: "stock", page: "rx", params: { product: 41 } }] } });
    expect(await screen.findByText("Amoksitsillin 500 mg kapsula №16")).toBeTruthy();
    fireEvent.change(screen.getByRole("textbox", { name: /Prescription number/ }), { target: { value: "RX-5512" } });
    fireEvent.change(screen.getByRole("textbox", { name: /Doctor/ }), { target: { value: "Dr. Saidova" } });
    fireEvent.change(screen.getByRole("textbox", { name: /Clinic/ }), { target: { value: "12-oilaviy poliklinika" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Kind of prescription" }), { target: { value: "psychotropic" } });
    const photo = new File(["jpeg"], "rx.jpg", { type: "image/jpeg" });
    fireEvent.change(document.querySelector('input[type="file"][capture]') as HTMLInputElement, { target: { files: [photo] } });
    fireEvent.click(screen.getByRole("button", { name: "Record" }));
    await waitFor(() => expect(calls("/stock/rx/")).toHaveLength(1));
    const body = calls("/stock/rx/")[0].body as Record<string, unknown>;
    expect(body).toMatchObject({
      product: 41,
      quantity: "1",
      prescription_number: "RX-5512",
      prescriber: "Dr. Saidova",
      facility: "12-oilaviy poliklinika",
      rx_kind: "psychotropic",
      status: "dispensed",
      photo,
    });
    expect(Object.keys(body).join(" ")).not.toMatch(/patient|pinfl|passport/i);
    expect(await screen.findByText("Recorded in the prescription log. No e-prescription number: flagged for the head")).toBeTruthy();
    expect(navigationState().stack).toEqual([{ feature: "stock", page: "product", params: { id: 41 } }]);
  });

  it("offers only prescription medicines and asks why a prescription is invalid", async () => {
    serve((path, method) => {
      if (path.includes("/stock/lookup/")) return [{ ...RX_PRODUCT, id: 60, name: "Vitamin C 500 mg", rx_required: false }, RX_PRODUCT];
      if (path.endsWith("/stock/rx/") && method === "POST") return { id: 4, flags: [] };
      return undefined;
    });
    renderApp(<RxPage params={{}} />, { me });
    fireEvent.change(await screen.findByRole("searchbox", { name: "Prescription medicine" }), { target: { value: "500" } });
    expect(await screen.findByRole("button", { name: /Amoksitsillin/ })).toBeTruthy();
    expect(screen.queryByText("Vitamin C 500 mg")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Amoksitsillin/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: "The prescription is invalid" }));
    const record = screen.getByRole("button", { name: "Record" }) as HTMLButtonElement;
    expect(record.disabled).toBe(true);
    fireEvent.change(screen.getByRole("textbox", { name: "What is wrong with it" }), { target: { value: "No stamp of the clinic" } });
    expect(record.disabled).toBe(false);
    fireEvent.click(record);
    await waitFor(() => expect(calls("/stock/rx/")).toHaveLength(1));
    expect(calls("/stock/rx/")[0].body).toMatchObject({ product: 41, status: "invalid", invalid_reason: "No stamp of the clinic" });
  });
});
