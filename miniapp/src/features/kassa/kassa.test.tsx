/**
 * Kassa end to end against a stubbed API: opening a shift with the float counted note by note,
 * a payout, the close draft surviving a reload, a close that retries after losing the signal,
 * the blind result, and answering a handover.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api/client";
import type { Me, Membership, Summary } from "../../api/types";
import { I18nProvider } from "../../i18n";
import { NavigationProvider } from "../../state/navigation";
import { SessionProvider, type Member } from "../../state/session";
import { ToastProvider } from "../../state/toast";
import type { Kassa, ShiftDetail } from "./api";
import ClosePage from "./ClosePage";
import { draftKey, emptyDraft, hasContent, photoStore, readDraft, writeDraft } from "./draft";
import { KassaHero } from "./KassaHero";
import KassaPage from "./KassaPage";
import { ReceivedCards } from "./Received";
import { PayoutSheet } from "./sheets";
import { features, findFeature } from "../registry";

// Through the registry, as the app loads it (the folder's index imports the registry).
const kassaFeature = findFeature(features, "kassa")!;

const client = vi.hoisted(() => ({ api: vi.fn(), apiForm: vi.fn() }));
// Making a photo smaller takes a moment on a phone: `delay` ms here (0 unless a test says).
const image = vi.hoisted(() => ({ delay: 0 }));
vi.mock("../../lib/image", () => ({
  downscale: (file: File) => new Promise<File>((resolve) => setTimeout(() => resolve(file), image.delay)),
}));
vi.mock("../../api/client", async (importOriginal) => {
  const real = await importOriginal<typeof import("../../api/client")>();
  return { ...real, api: client.api, apiForm: client.apiForm };
});

const membership = {
  id: 7,
  company: { id: 1, name: "Demo Dorixona", timezone: "Asia/Tashkent", features: ["sales"], base_currency: "UZS" },
  status: "approved",
  first_name: "Madina",
  last_name: "Saidova",
  position: null,
  role: "Cashier",
  permissions: ["sales.operate"],
  is_onboarded: true,
  onboarded_at: null,
  decided_at: null,
  rejoin_available_at: null,
} as unknown as Membership;
const me = { id: 1, telegram_id: 1004, telegram_username: "", first_name: "Madina", last_name: "Saidova", phone: "", language: "en", memberships: [membership] } as Me;
const member: Member = { ...membership, timeZone: "Asia/Tashkent", companyId: 1 };

const branch = { id: 3, name: "Chilonzor", code: "CH" };

function shift(extra: Partial<ShiftDetail> = {}): ShiftDetail {
  return {
    id: 5,
    code: "CH-12",
    status: "open",
    branch,
    register: { id: 1, name: "Kassa 1" },
    business_day: "2026-10-21",
    opened_at: "2026-10-21T04:40:00Z",
    closed_at: null,
    opening_float: "200000.00",
    net: "0.00",
    receipts: 0,
    counted_cash: null,
    expected_cash: null,
    difference: null,
    verified_at: null,
    verified_by: null,
    note: "",
    forced: false,
    payments: [],
    opening_count: {},
    closing_count: {},
    z_number: "",
    cashier_note: "",
    movements: [],
    moved: {},
    receipts_recorded: {},
    entries: [],
    photos: { z_photo: null, terminal_photo: null },
    ...extra,
  };
}

function kassa(extra: Partial<Kassa> = {}): Kassa {
  return {
    shift: null,
    settings: { mode: "shift_totals", blind_cash_count: true, require_z_photo: false, require_terminal_photo: false, currency: "UZS" },
    registers: [
      { id: 1, name: "Kassa 1", branch, busy: null },
      { id: 2, name: "Kassa 2", branch, busy: { code: "CH-11", cashier: "Jasur Tursunov" } },
    ],
    methods: [
      { id: 11, name: "Cash", kind: "cash" },
      { id: 12, name: "Uzcard", kind: "card" },
    ],
    receivers: [{ id: 2, name: "Dilnoza Karimova", role: "Owner" }],
    categories: [
      { id: 31, name: "Other", code: "other_expense" },
      { id: 30, name: "Goods", code: "goods" },
    ],
    pending_handovers: [],
    recent: [],
    ...extra,
  };
}

/** Answer GETs from a table; anything else goes to `post`. */
function serve(gets: Record<string, unknown>, post: (path: string, options: { method?: string; json?: unknown }) => unknown = () => ({})) {
  client.api.mockImplementation(async (path: string, options: { method?: string; json?: unknown } = {}) => {
    if (!options.method || options.method === "GET") {
      const key = Object.keys(gets).find((suffix) => path.endsWith(suffix));
      if (key === undefined) throw new Error(`unexpected GET ${path}`);
      return gets[key];
    }
    return post(path, options);
  });
}

function wrap(children: ReactNode, person: Me = me) {
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } } });
  const view = render(
    <QueryClientProvider client={queries}>
      <I18nProvider lang="en">
        <SessionProvider me={person}>
          <NavigationProvider>
            <ToastProvider>
              <div className="app">{children}</div>
            </ToastProvider>
          </NavigationProvider>
        </SessionProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
  return Object.assign(view, { queries });
}

beforeEach(() => {
  localStorage.clear();
  image.delay = 0;
  vi.stubGlobal("confirm", () => true);
});

afterEach(() => {
  cleanup();
  client.api.mockReset();
  client.apiForm.mockReset();
  vi.unstubAllGlobals();
});

describe("opening a shift", () => {
  it("picks the free till and sends the float counted note by note", async () => {
    serve({ "/sales/shifts/current/": kassa(), "/sales/handovers/pending/": { results: [] } }, () => shift());
    wrap(<KassaPage params={{}} />);
    expect(await screen.findByRole("heading", { name: "Open a shift" })).toBeTruthy();
    // The busy till says who has it and can't be picked; the only free one is picked already.
    expect(screen.getByText("Open: Jasur Tursunov · CH-11")).toBeTruthy();
    expect(screen.getByRole("radio", { name: /Kassa 2/ }).hasAttribute("disabled")).toBe(true);
    expect(screen.getByRole("radio", { name: /Kassa 1/ }).getAttribute("aria-checked")).toBe("true");

    const tenThousands = screen.getByRole("group", { name: "10,000" });
    fireEvent.click(within(tenThousands).getByRole("button", { name: "More" }));
    fireEvent.click(within(tenThousands).getByRole("button", { name: "More" }));
    fireEvent.click(within(screen.getByRole("group", { name: "1,000" })).getByRole("button", { name: "More" }));
    fireEvent.click(screen.getByRole("button", { name: /Open shift · 21,000\sUZS/ }));

    await waitFor(() =>
      expect(client.api).toHaveBeenCalledWith("/companies/1/sales/shifts/", {
        method: "POST",
        json: { register_id: 1, opening_count: { "10000": 2, "1000": 1 }, opening_float: "21000.00" },
      }),
    );
  });

  it("says where a busy till is when tills of several branches share a name", async () => {
    const yunusobod = { id: 4, name: "Yunusobod", code: "YN" };
    const registers = [
      { id: 1, name: "Kassa 1", branch, busy: null },
      { id: 3, name: "Kassa 1", branch: yunusobod, busy: { code: "YN-11", cashier: "Jasur Tursunov" } },
    ];
    serve({ "/sales/shifts/current/": kassa({ registers }), "/sales/handovers/pending/": { results: [] } });
    wrap(<KassaPage params={{}} />);
    expect(await screen.findByText("Yunusobod · Open: Jasur Tursunov · YN-11")).toBeTruthy();
  });

  it("says every till is open instead of asking to pick one when none is free", async () => {
    const registers = [{ id: 2, name: "Kassa 2", branch, busy: { code: "CH-11", cashier: "Jasur Tursunov" } }];
    serve({ "/sales/shifts/current/": kassa({ registers }), "/sales/handovers/pending/": { results: [] } });
    wrap(<KassaPage params={{}} />);
    const action = await screen.findByRole("button", { name: /Every till is open/ });
    expect(action.hasAttribute("disabled")).toBe(true);
    expect(screen.queryByRole("button", { name: /Pick a till/ })).toBeNull();
  });

  it("can take a typed total instead of counted notes", async () => {
    serve({ "/sales/shifts/current/": kassa(), "/sales/handovers/pending/": { results: [] } }, () => shift());
    wrap(<KassaPage params={{}} />);
    fireEvent.click(await screen.findByRole("button", { name: "Type the total instead" }));
    for (const key of ["3", "5", "000"]) fireEvent.click(screen.getByRole("button", { name: key }));
    fireEvent.click(screen.getByRole("button", { name: /Open shift · 35,000\sUZS/ }));
    await waitFor(() =>
      expect(client.api).toHaveBeenCalledWith("/companies/1/sales/shifts/", { method: "POST", json: { register_id: 1, opening_count: undefined, opening_float: "35000" } }),
    );
  });
});

describe("during a shift", () => {
  it("records a payout with its category and reason", async () => {
    serve({ "/sales/shifts/current/": kassa({ shift: shift() }) });
    client.apiForm.mockResolvedValue({ id: 99 });
    const close = vi.fn();
    wrap(<PayoutSheet params={{}} close={close} />);
    fireEvent.change(await screen.findByLabelText("Amount"), { target: { value: "120000" } });
    fireEvent.change(screen.getByLabelText("Details"), { target: { value: "Courier for a prescription delivery" } });
    // Goods comes first: a till pays for goods more than anything.
    expect(screen.getByRole("button", { name: "Goods" }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: /Pay out 120,000\sUZS/ }));
    await waitFor(() =>
      expect(client.apiForm).toHaveBeenCalledWith("/companies/1/sales/shifts/5/movements/", {
        kind: "payout",
        amount: "120000",
        category_id: 30,
        reason: "Courier for a prescription delivery",
        photo: null,
      }),
    );
    await waitFor(() => expect(close).toHaveBeenCalled());
  });

  it("sends one payout for a double tap, even while the receipt photo is made smaller", async () => {
    serve({ "/sales/shifts/current/": kassa({ shift: shift() }) });
    client.apiForm.mockResolvedValue({ id: 99 });
    image.delay = 100;
    wrap(<PayoutSheet params={{}} close={() => undefined} />);
    fireEvent.change(await screen.findByLabelText("Amount"), { target: { value: "120000" } });
    fireEvent.change(screen.getByLabelText("Details"), { target: { value: "Courier" } });
    const receipt = new File(["photo"], "receipt.jpg", { type: "image/jpeg" });
    fireEvent.change(document.querySelector('input[type="file"]')!, { target: { files: [receipt] } });
    // Two quick taps, a finger's 30 ms apart.
    const pay = screen.getByRole("button", { name: /Pay out 120,000\sUZS/ });
    fireEvent.click(pay);
    await new Promise((resolve) => setTimeout(resolve, 30));
    fireEvent.click(pay);
    await waitFor(() => expect(client.apiForm).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 150));
    expect(client.apiForm).toHaveBeenCalledTimes(1);
    expect(client.apiForm.mock.calls[0][1]).toEqual(expect.objectContaining({ photo: receipt }));
  });

  it("keeps a half-filled payout and the shift on screen when a refetch behind them fails", async () => {
    serve({ "/sales/shifts/current/": kassa({ shift: shift() }) });
    const { queries } = wrap(<PayoutSheet params={{}} close={() => undefined} />);
    fireEvent.change(await screen.findByLabelText("Amount"), { target: { value: "120000" } });
    // Back from the camera the till is fetched again, and this time the signal is gone.
    client.api.mockRejectedValue(new TypeError("Failed to fetch"));
    await act(async () => {
      await queries.refetchQueries();
      // The failure reaches the screen a moment later.
      await new Promise((resolve) => setTimeout(resolve, 50));
    });
    expect(queries.getQueryState(["kassa", 1, "current"])?.status).toBe("error");
    expect((screen.getByLabelText("Amount") as HTMLInputElement).value).toMatch(/120[\s,.]?000/);
    expect(screen.queryByText("Kassa didn’t load")).toBeNull();
  });

  it("gives each of two receipts voided at once its own answer, a refusal included", async () => {
    const entry = (id: number, total: string) => ({ id, kind: "sale" as const, total, number: "", sold_at: "2026-10-21T06:00:00Z", voided_at: null, methods: [{ id: 11, name: "Cash", amount: total }] });
    const receipts = { ...kassa().settings, mode: "receipts" as const };
    serve({ "/sales/shifts/current/": kassa({ settings: receipts, shift: shift({ entries: [entry(1, "15000.00"), entry(2, "27000.00")] }) }) }, (path) =>
      path.endsWith("/entries/1/void/")
        ? new Promise((_, reject) => setTimeout(() => reject(new ApiError(400, { detail: "Too late to void it" })), 60))
        : Promise.resolve({ id: 2 }),
    );
    wrap(<KassaPage params={{}} />);
    const [first, second] = await screen.findAllByRole("button", { name: "Void" });
    fireEvent.click(first);
    await waitFor(() => expect((first as HTMLButtonElement).disabled).toBe(true));
    fireEvent.click(second);
    // The second answer doesn't silence the first, nor free its button early.
    expect(await screen.findByText("Too late to void it")).toBeTruthy();
  });

  it("shows the open shift on Home with its actions, and no cash total", async () => {
    serve({ "/sales/shifts/current/": kassa({ shift: shift() }) });
    wrap(<KassaHero member={member} summary={undefined} />);
    expect(await screen.findByText("Kassa 1")).toBeTruthy();
    expect(screen.getByText(/Shift open · CH-12/)).toBeTruthy();
    for (const name of ["Hand over", "Payout", "Close shift"]) expect(screen.getByRole("button", { name })).toBeTruthy();
  });

  it("asks to open the till on Home, except on a day off, when an open shift still shows", async () => {
    const off = { off_today: { kind: "time_off", name: "", until: "2026-10-22" } } as unknown as Summary;
    serve({ "/sales/shifts/current/": kassa() });
    const working = wrap(<KassaHero member={member} summary={undefined} />);
    expect(await screen.findByText("Kassa is closed")).toBeTruthy();
    working.unmount();

    // "You're off today" is on Home: no "Open shift" beside it.
    const resting = wrap(<KassaHero member={member} summary={off} />);
    await waitFor(() => expect(client.api).toHaveBeenCalled());
    await waitFor(() => expect(resting.container.querySelector(".skeleton")).toBeNull());
    expect(screen.queryByText("Kassa is closed")).toBeNull();
    resting.unmount();

    serve({ "/sales/shifts/current/": kassa({ shift: shift() }) });
    wrap(<KassaHero member={member} summary={off} />);
    expect(await screen.findByText(/Shift open · CH-12/)).toBeTruthy();
  });

  it("says who has the till when colleagues have every till open, with nothing to press", async () => {
    const taken = { code: "CH-11", cashier: "Jasur Tursunov" };
    serve({ "/sales/shifts/current/": kassa({ registers: [{ id: 2, name: "Kassa 2", branch, busy: taken }] }) });
    const one = wrap(<KassaHero member={member} summary={undefined} />);
    expect(await screen.findByText("Kassa 2 is open")).toBeTruthy();
    expect(screen.getByText("Jasur Tursunov has it · CH-11")).toBeTruthy();
    expect(screen.queryByText("Open shift")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
    one.unmount();

    serve({
      "/sales/shifts/current/": kassa({
        registers: [
          { id: 2, name: "Kassa 2", branch, busy: taken },
          { id: 3, name: "Kassa 3", branch, busy: { code: "CH-13", cashier: "Nigora Azimova" } },
        ],
      }),
    });
    wrap(<KassaHero member={member} summary={undefined} />);
    expect(await screen.findByText("Every till is open")).toBeTruthy();
    expect(screen.getByText("Jasur Tursunov, Nigora Azimova")).toBeTruthy();
  });
});

describe("closing", () => {
  it("keeps the draft through a reload", async () => {
    serve({ "/sales/shifts/current/": kassa({ shift: shift() }) });
    const first = wrap(<ClosePage params={{ id: 5 }} />);
    expect(await screen.findByRole("heading", { name: "Close shift CH-12" })).toBeTruthy();
    for (const key of ["4", "5", "0", "000"]) fireEvent.click(screen.getByRole("button", { name: key }));
    expect(screen.getAllByText("450,000").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("tab", { name: /Uzcard/ }));
    for (const key of ["9", "0", "000"]) fireEvent.click(screen.getByRole("button", { name: key }));
    first.unmount();

    // The app is opened again: everything typed is back, with a note saying so.
    wrap(<ClosePage params={{ id: 5 }} />);
    expect(await screen.findByText(/We kept what you entered at/)).toBeTruthy();
    expect(within(screen.getByRole("tab", { name: /Cash/ })).getByText("450,000")).toBeTruthy();
    expect(within(screen.getByRole("tab", { name: /Uzcard/ })).getByText("90,000")).toBeTruthy();
    expect(readDraft(1, 5)?.lines).toEqual({ "11": { sales: "450000", refunds: "" }, "12": { sales: "90000", refunds: "" } });
  });

  it("asks for a Z-report photo when the company requires one", async () => {
    serve({ "/sales/shifts/current/": kassa({ shift: shift(), settings: { ...kassa().settings, require_z_photo: true } }) });
    writeDraft(1, 5, { ...emptyDraft(), step: "z" });
    wrap(<ClosePage params={{ id: 5 }} />);
    expect(await screen.findByText("Add the Z-report photo to go on.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Next: count the cash" }).hasAttribute("disabled")).toBe(true);
  });

  it("sends the close, waits out a lost signal, and shows the blind result", async () => {
    serve({ "/sales/shifts/current/": kassa({ shift: shift() }) });
    writeDraft(1, 5, {
      ...emptyDraft(),
      step: "review",
      lines: { "11": { sales: "450000", refunds: "" }, "12": { sales: "90000", refunds: "5000" } },
      counts: { "100000": 4, "50000": 1 },
      receipts: "37",
      zNumber: "0412",
    });
    client.apiForm.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    client.apiForm.mockResolvedValueOnce(shift({ status: "closed", closed_at: "2026-10-21T16:05:00Z", counted_cash: "450000.00", receipts: 37 }));
    wrap(<ClosePage params={{ id: 5 }} />);

    // The review shows what goes, and the cash counted, but nothing about what was expected.
    expect(await screen.findByText("Cash counted")).toBeTruthy();
    expect(screen.getByText("535,000 UZS")).toBeTruthy();
    fireEvent.keyDown(screen.getByRole("button", { name: "Slide to close the shift" }), { key: "Enter" });

    expect(await screen.findByText("No connection. Your close is safe on this phone.")).toBeTruthy();
    expect(readDraft(1, 5)?.pending).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Send now" }));

    expect(await screen.findByRole("heading", { name: "Shift closed" })).toBeTruthy();
    expect(screen.getByText("Your manager checks the count")).toBeTruthy();
    expect(screen.queryByText(/Short by|Over by|Expected/)).toBeNull();
    expect(client.apiForm).toHaveBeenLastCalledWith("/companies/1/sales/shifts/5/close/", {
      counted_cash: "450000.00",
      receipts: 37,
      z_number: "0412",
      note: "",
      z_photo: null,
      terminal_photo: null,
      payments: JSON.stringify([
        { method_id: 11, sales: "450000", refunds: "0" },
        { method_id: 12, sales: "90000", refunds: "5000" },
      ]),
      closing_count: JSON.stringify({ "100000": 4, "50000": 1 }),
    });
    expect(localStorage.getItem(draftKey(1, 5))).toBeNull();
  });

  it("sends a close resumed after a reload with the photos kept on the phone, once they are read back", async () => {
    serve({ "/sales/shifts/current/": kassa({ shift: shift(), settings: { ...kassa().settings, require_z_photo: true } }) });
    writeDraft(1, 5, { ...emptyDraft(), step: "review", counts: { "200000": 1 }, pending: true });
    const zReport = new File(["z"], "z.jpg", { type: "image/jpeg" });
    // IndexedDB answers a moment after the screen is up.
    vi.spyOn(photoStore, "get").mockImplementation(
      (key) => new Promise((resolve) => setTimeout(() => resolve(key.endsWith(".z") ? zReport : null), 30)),
    );
    client.apiForm.mockResolvedValueOnce(shift({ status: "closed", closed_at: "2026-10-21T16:05:00Z", counted_cash: "200000.00" }));
    wrap(<ClosePage params={{ id: 5 }} />);
    expect(await screen.findByRole("heading", { name: "Shift closed" })).toBeTruthy();
    expect(client.apiForm).toHaveBeenCalledTimes(1);
    expect(client.apiForm.mock.calls[0][1]).toEqual(expect.objectContaining({ z_photo: zReport }));
  });

  it("doesn't let Start over empty a close that is still going out", async () => {
    serve({ "/sales/shifts/current/": kassa({ shift: shift() }) });
    writeDraft(1, 5, { ...emptyDraft(), step: "review", counts: { "200000": 1 }, zNumber: "0412", pending: true, savedAt: "2026-10-21T16:00:00Z" });
    client.apiForm.mockRejectedValue(new TypeError("Failed to fetch"));
    wrap(<ClosePage params={{ id: 5 }} />);
    expect(await screen.findByText("No connection. Your close is safe on this phone.")).toBeTruthy();
    // Its next try would send whatever the draft holds then: the button waits.
    expect((screen.getByRole("button", { name: "Start over" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("sends a close left pending by a reload as soon as the screen is back", async () => {
    serve({ "/sales/shifts/current/": kassa({ shift: shift() }) });
    writeDraft(1, 5, { ...emptyDraft(), step: "review", counts: { "200000": 1 }, pending: true });
    client.apiForm.mockResolvedValueOnce(shift({ status: "closed", closed_at: "2026-10-21T16:05:00Z", counted_cash: "200000.00" }));
    wrap(<ClosePage params={{ id: 5 }} />);
    expect(await screen.findByRole("heading", { name: "Shift closed" })).toBeTruthy();
    expect(client.apiForm).toHaveBeenCalledTimes(1);
  });
});

describe("handovers", () => {
  it("confirms cash handed to me", async () => {
    const handover = {
      id: 9,
      amount: "1300000.00",
      currency: "UZS",
      from: { id: 4, name: "Madina Saidova" },
      branch,
      register: { id: 1, name: "Kassa 1" },
      reason: "Kunlik tushum",
      created_at: new Date(Date.now() - 30 * 60_000).toISOString(),
    };
    serve({ "/sales/handovers/pending/": { results: [handover] } }, () => ({ id: 9, status: "done" }));
    wrap(<ReceivedCards member={member} summary={undefined} />);
    expect(await screen.findByText("Did you get 1,300,000 UZS?")).toBeTruthy();
    expect(screen.getByText("From Madina Saidova · Chilonzor, Kassa 1 · 30 min ago")).toBeTruthy();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Yes, I got it" }));
    });
    await waitFor(() =>
      expect(client.api).toHaveBeenCalledWith("/companies/1/sales/handovers/9/confirm/", { method: "POST", json: { reason: "" } }),
    );
  });
});

describe("answering a handover over a slow connection", () => {
  const handover = {
    id: 9,
    amount: "1300000.00",
    currency: "UZS",
    from: { id: 4, name: "Madina Saidova" },
    branch,
    register: { id: 1, name: "Kassa 1" },
    reason: "",
    created_at: new Date(Date.now() - 30 * 60_000).toISOString(),
  };

  it("says it went through, though the card left the moment it was answered", async () => {
    const slow = <T,>(value: T) => new Promise<T>((resolve) => setTimeout(() => resolve(value), 80));
    serve({ "/sales/handovers/pending/": { results: [handover] } }, () => slow({ id: 9, status: "done" }));
    wrap(<ReceivedCards member={member} summary={undefined} />);
    fireEvent.click(await screen.findByRole("button", { name: "Yes, I got it" }));
    expect(await screen.findByText(/Thanks\. 1,300,000\sUZS is with you now\./)).toBeTruthy();
  });

  it("brings the card back and says why when the answer didn't go", async () => {
    serve({ "/sales/handovers/pending/": { results: [handover] } }, () =>
      new Promise((_, reject) => setTimeout(() => reject(new TypeError("Failed to fetch")), 80)),
    );
    wrap(<ReceivedCards member={member} summary={undefined} />);
    fireEvent.click(await screen.findByRole("button", { name: "Yes, I got it" }));
    expect(await screen.findByText(/No connection/)).toBeTruthy();
    expect(await screen.findByRole("button", { name: "Yes, I got it" })).toBeTruthy();
  });
});

describe("without till access", () => {
  const worker = { ...membership, permissions: [] } as unknown as Membership;
  const workerMe = { ...me, memberships: [worker] } as Me;
  const handover = {
    id: 9,
    amount: "1300000.00",
    currency: "UZS",
    from: { id: 4, name: "Madina Saidova" },
    branch,
    register: { id: 1, name: "Kassa 1" },
    reason: "",
    created_at: new Date(Date.now() - 30 * 60_000).toISOString(),
  };

  it("says so on the Kassa page without asking for the till, and keeps cash handed to me", async () => {
    serve({ "/sales/handovers/pending/": { results: [handover] } });
    const Page = kassaFeature.pages!.home!;
    wrap(<Page params={{}} />, workerMe);
    expect(await screen.findByText("The till isn’t open to you")).toBeTruthy();
    expect(await screen.findByText("Did you get 1,300,000 UZS?")).toBeTruthy();
    expect(client.api.mock.calls.map(([path]) => path)).toEqual(["/companies/1/sales/handovers/pending/"]);
  });

  it("never loads a shift, the history or a till sheet", async () => {
    serve({});
    const ShiftView = kassaFeature.pages!.shift!;
    const History = kassaFeature.pages!.history!;
    const Payout = kassaFeature.sheets!.payout!;
    wrap(
      <>
        <ShiftView params={{ id: 5 }} />
        <History params={{}} />
        <Payout params={{}} close={() => undefined} />
      </>,
      workerMe,
    );
    expect(await screen.findAllByText("The till isn’t open to you")).toHaveLength(3);
    expect(client.api).not.toHaveBeenCalled();
  });

  it("still opens for a cashier", async () => {
    serve({ "/sales/shifts/current/": kassa(), "/sales/handovers/pending/": { results: [] } });
    const Page = kassaFeature.pages!.home!;
    wrap(<Page params={{}} />);
    expect(await screen.findByRole("heading", { name: "Open a shift" })).toBeTruthy();
  });
});

describe("the draft store", () => {
  it("ignores what it can't read and knows an empty draft", () => {
    localStorage.setItem(draftKey(1, 5), "{not json");
    expect(readDraft(1, 5)).toBeNull();
    localStorage.setItem(draftKey(1, 5), JSON.stringify({ v: 2 }));
    expect(readDraft(1, 5)).toBeNull();
    expect(hasContent(emptyDraft())).toBe(false);
    expect(hasContent({ ...emptyDraft(), counts: { "1000": 3 } })).toBe(true);
    writeDraft(1, 5, { ...emptyDraft(), zNumber: "12" });
    expect(readDraft(1, 5)?.zNumber).toBe("12");
  });
});
