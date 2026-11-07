/**
 * The expiry check (PLAN-OWNER §14.17): my pharmacy's batches in the company's groups (expired,
 * then each step), "On the near-expiry shelf" and "Propose write-off" shown at once and rolled
 * back with the server's reason on an error, marks kept on the phone, and an empty list said kindly.
 */
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api/client";
import { membership, navigationState, person, renderApp } from "../../test/harness";
import type { AppBatch } from "./api";
import ExpiryPage, { groupRows } from "./ExpiryPage";
import { readMarks, writeMarks } from "./marks";
import { reasonsFor } from "./WriteOffSheet";

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

function batch(id: number, days: number, over: Partial<AppBatch> = {}): AppBatch {
  return {
    id,
    batch_id: id + 100,
    branch_id: 1,
    branch: "Chilonzor",
    series: `S-${id}`,
    expires_on: "2026-12-01",
    days_left: days,
    expired: days < 0,
    status: "sellable",
    quantity: "5.000",
    retail_price: "18000.00",
    part_price: "9000.00",
    product: { id: id + 40, name: `Medicine ${id}` },
    units_per_pack: 2,
    part_label: "blister",
    ...over,
  };
}

const ROWS = [batch(1, -4), batch(2, 12), batch(3, 0), batch(4, 45), batch(5, 80)];

/** A reply the test lets go of when it wants to: what the screen shows meanwhile is the point. */
function later<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function serve(action: (path: string, body: unknown) => unknown = () => ({ action: "on_shelf", writeoff_id: null }), rows: AppBatch[] = ROWS) {
  server.handler = (path, method, body) => {
    if (path.endsWith("/stock/settings/")) return { camera_scanning: false, show_other_branches: true, rx_log: true, fefo_strict: true };
    if (path.includes("/stock/expiry/")) return rows;
    if (path.includes("/expiry-action/") && method === "POST") return action(path, body);
    return undefined;
  };
}

const cards = () => screen.getAllByTestId("expiry-row");

beforeEach(() => {
  server.calls = [];
  localStorage.clear();
  serve();
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: (file: File) => `blob:${file.name}` });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: () => undefined });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  delete (URL as unknown as Record<string, unknown>).createObjectURL;
  delete (URL as unknown as Record<string, unknown>).revokeObjectURL;
});

describe("expiry groups", () => {
  it("puts each batch in one group, soonest first", () => {
    const groups = groupRows(ROWS, [30, 60, 90]);
    expect([...groups.keys()]).toEqual(["expired", "30", "60", "90"]);
    expect(groups.get("expired")!.map((row) => row.id)).toEqual([1]);
    expect(groups.get("30")!.map((row) => row.id)).toEqual([3, 2]);
    expect(groups.get("60")!.map((row) => row.id)).toEqual([4]);
    expect(groups.get("90")!.map((row) => row.id)).toEqual([5]);
  });

  it("offers expired goods only as expired", () => {
    expect(reasonsFor(batch(1, -1))).toEqual(["expired"]);
    expect(reasonsFor(batch(1, 10, { status: "recalled" }))).toEqual(["recall", "quality", "other"]);
    expect(reasonsFor(batch(1, 10))).toEqual(["damaged", "quality", "other"]);
  });
});

describe("the expiry check", () => {
  it("opens on the expired ones, counts each group and asks for the company's longest step", async () => {
    renderApp(<ExpiryPage />, { me });
    const tabs = await screen.findByRole("tablist");
    expect(within(tabs).getAllByRole("tab").map((tab) => tab.textContent)).toEqual(["Expired1", "30 days2", "60 days1", "90 days1"]);
    expect(server.calls.some((call) => call.path.endsWith("/stock/expiry/?within=90"))).toBe(true);
    expect(cards()).toHaveLength(1);
    const expired = cards()[0];
    expect(expired.textContent).toContain("Medicine 1");
    expect(expired.textContent).toContain("Series S-1 · expired 01.12.2026 · On hand: 2 packs 1 blister");
    // Expired goods go off the shelf: only the write-off is offered.
    expect(within(expired).queryByRole("button", { name: "On the near-expiry shelf" })).toBeNull();
    expect(within(expired).getByRole("button", { name: "Propose write-off" })).toBeTruthy();

    fireEvent.click(within(tabs).getByRole("tab", { name: /30 days/ }));
    expect(cards().map((card) => card.querySelector(".stk-exp-title")?.textContent)).toEqual(["Medicine 3", "Medicine 2"]);
    expect(screen.getByText("Expire within 30 days: put them on the near-expiry shelf.")).toBeTruthy();
    fireEvent.click(within(tabs).getByRole("tab", { name: /60 days/ }));
    expect(screen.getByText("Expire in 31–60 days.")).toBeTruthy();
  });

  it("marks a batch on the shelf at once and keeps the mark on the phone", async () => {
    const reply = later<unknown>();
    serve(() => reply.promise);
    renderApp(<ExpiryPage />, { me });
    fireEvent.click(within(await screen.findByRole("tablist")).getByRole("tab", { name: /30 days/ }));
    const first = cards()[0];
    fireEvent.click(within(first).getByRole("button", { name: "On the near-expiry shelf" }));
    // Before the server answers.
    expect(await within(first).findByText("On the shelf")).toBeTruthy();
    const call = server.calls.find((item) => item.path.includes("/expiry-action/"))!;
    expect(call.path).toBe("/companies/1/stock/batches/3/expiry-action/");
    expect(call.body).toEqual({ action: "on_shelf" });
    await act(async () => reply.resolve({ action: "on_shelf", writeoff_id: null }));
    await waitFor(() => expect(readMarks(1)[3]?.shelf).toMatch(/^\d{4}-\d{2}-\d{2}$/));
    expect(within(first).getByText("On the shelf")).toBeTruthy();
  });

  it("takes the mark back with the server's reason when it refuses", async () => {
    serve(() => new ApiError(400, { detail: "None of this series is here any more." }));
    renderApp(<ExpiryPage />, { me });
    fireEvent.click(within(await screen.findByRole("tablist")).getByRole("tab", { name: /30 days/ }));
    fireEvent.click(within(cards()[0]).getByRole("button", { name: "On the near-expiry shelf" }));
    expect(await screen.findByText("None of this series is here any more.")).toBeTruthy();
    expect(within(cards()[0]).getByRole("button", { name: "On the near-expiry shelf" })).toBeTruthy();
    expect(readMarks(1)[3]).toBeUndefined();
  });

  it("proposes a write-off with a photo: the row says so at once", async () => {
    const reply = later<unknown>();
    serve(() => reply.promise);
    renderApp(<ExpiryPage />, { me });
    await screen.findByRole("tablist");
    fireEvent.click(within(cards()[0]).getByRole("button", { name: "Propose write-off" }));
    expect(navigationState().sheet).toEqual({ kind: "feature", feature: "stock", sheet: "writeoff", params: { id: 1, within: 90 } });
    expect(await screen.findByText("All of series S-1 here: 2 packs 1 blister.")).toBeTruthy();
    const file = new File(["jpeg"], "packs.jpg", { type: "image/jpeg" });
    const input = document.querySelector('input[type="file"][capture]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });
    fireEvent.click(screen.getAllByRole("button", { name: "Propose write-off" }).at(-1)!);
    await waitFor(() => expect(navigationState().sheet).toBeNull());
    expect(await within(cards()[0]).findByText("Sending…")).toBeTruthy();
    const call = server.calls.find((item) => item.path.includes("/expiry-action/"))!;
    expect(call.path).toBe("/companies/1/stock/batches/1/expiry-action/");
    expect(call.body).toEqual({ action: "propose_writeoff", reason: "expired", photo: file });
    await act(async () => reply.resolve({ action: "propose_writeoff", writeoff_id: 88 }));
    expect(await screen.findByText("Write-off proposed")).toBeTruthy();
    expect(await screen.findByText("Write-off proposed: the head approves it")).toBeTruthy();
    expect(readMarks(1)[1]).toEqual({ writeoff: 88 });
  });

  it("puts the row back when the proposal is refused", async () => {
    serve(() => new ApiError(400, { action: ["None of this series is here any more."] }));
    renderApp(<ExpiryPage />, { me });
    await screen.findByRole("tablist");
    fireEvent.click(within(cards()[0]).getByRole("button", { name: "Propose write-off" }));
    await screen.findByText("All of series S-1 here: 2 packs 1 blister.");
    fireEvent.click(screen.getAllByRole("button", { name: "Propose write-off" }).at(-1)!);
    expect(await screen.findByText("None of this series is here any more.")).toBeTruthy();
    expect(within(cards()[0]).getByRole("button", { name: "Propose write-off" })).toBeTruthy();
    expect(readMarks(1)[1]).toBeUndefined();
    expect(server.calls.find((item) => item.path.includes("/expiry-action/"))!.body).toEqual({ action: "propose_writeoff", reason: "expired" });
  });

  it("remembers what this phone marked after a reload", async () => {
    writeMarks(1, { 1: { writeoff: 70 }, 2: { shelf: "2026-11-06" } });
    renderApp(<ExpiryPage />, { me });
    await screen.findByRole("tablist");
    expect(within(cards()[0]).getByText("Write-off proposed")).toBeTruthy();
    fireEvent.click(within(screen.getByRole("tablist")).getByRole("tab", { name: /30 days/ }));
    expect(within(cards()[1]).getByText("On the shelf")).toBeTruthy();
  });

  it("says when nothing expires soon, and shows a reader no buttons", async () => {
    serve(undefined, []);
    renderApp(<ExpiryPage />, { me });
    expect(await screen.findByText("Nothing expires soon")).toBeTruthy();
    expect(screen.getByText("No batch here expires within 90 days.")).toBeTruthy();
    cleanup();

    serve();
    renderApp(<ExpiryPage />, { me: person([membership({ company, permissions: ["sales.view"] } as never)]) });
    await screen.findByRole("tablist");
    expect(screen.queryByRole("button", { name: "Propose write-off" })).toBeNull();
  });

  it("works before the server names the item: the series stands in", async () => {
    serve(undefined, [batch(9, -2, { product: undefined, units_per_pack: undefined, part_label: undefined })]);
    renderApp(<ExpiryPage />, { me });
    await screen.findByRole("tablist");
    expect(cards()[0].querySelector(".stk-exp-title")?.textContent).toBe("Series S-9");
    expect(cards()[0].textContent).toContain("On hand: 5 parts");
  });
});
