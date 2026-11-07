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
import { blind, type Count, type IncomingTransfer } from "./api";
import CountPage from "./CountPage";
import CountsPage from "./CountsPage";
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
