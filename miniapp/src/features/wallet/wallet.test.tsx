/**
 * "My pay": what each card shows, the dispute and advance forms (their checks and the bodies they
 * send), the payslip's "I received it", the Home cards and Me row, and the bot's deep links.
 */
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api/client";
import { resolveScreen } from "../../state/deeplink";
import { membership, navigationState, person, renderApp } from "../../test/harness";
import { features, featureVisible, findFeature } from "../registry";
import type { Adjustment, Advance, Earnings, MyAdvances, Payslip, PayslipRow, Progress } from "./api";
import { walletKeys } from "./api";
import {
  addMonths,
  advanceDraft,
  byMonth,
  canDispute,
  disputePayload,
  disputeStage,
  homePay,
  partRows,
  payslipState,
  payslipsToSee,
  payslipToAsk,
  plainNumber,
  progressView,
  repaymentMonths,
} from "./lib";
import PayslipPage from "./PayslipPage";
import { AdjustmentSheet, AdvanceRequestSheet, AdvanceSheet } from "./sheets";
import { MonthCard, PayslipCard } from "./slots";
import WalletPage from "./WalletPage";

const client = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("../../api/client", async (importOriginal) => {
  const real = await importOriginal<typeof import("../../api/client")>();
  return { ...real, api: client.api };
});

const wallet = findFeature(features, "wallet")!;
const company = { id: 1, name: "Demo Dorixona", timezone: "Asia/Tashkent", features: ["payroll", "hr"], base_currency: "UZS" };
const alisher = membership({ company } as never);
const me = person([alisher]);
const member = { ...alisher, timeZone: "Asia/Tashkent", companyId: 1 };

const sums = (net: string, extra: Partial<Earnings["so_far"]> = {}): Earnings["so_far"] => ({
  base: "650000.00",
  extra: "0.00",
  pieces: "0.00",
  bonuses: "0.00",
  fines: "0.00",
  taxes: "0.00",
  advances: "0.00",
  reimbursements: "0.00",
  net,
  ...extra,
});

function earnings(extra: Partial<Earnings> = {}): Earnings {
  return {
    period: "2026-11-01",
    as_of: "2026-11-02",
    currency: "UZS",
    has_pay_setup: true,
    pay_type: "monthly",
    so_far: sums("3450000.00", { base: "3450000.00" }),
    estimate: sums("5200000.00", { base: "5200000.00" }),
    worked_minutes: 0,
    scheduled_days: 26,
    absent_days: 0,
    proposed: [],
    progress: [],
    ...extra,
  };
}

function adjustment(extra: Partial<Adjustment> = {}): Adjustment {
  return {
    id: 11,
    member: { id: 7, name: "Alisher Valiyev", photo_url: null },
    period: "2026-11-01",
    kind: "fine",
    amount: "100000.00",
    currency: "UZS",
    reason: "Kassa hisobotida 100 000 so‘m kamomad",
    source: "manual",
    rule: null,
    task: null,
    status: "approved",
    proposed_by: "Bekzod Mirzayev",
    created_at: "2026-11-01T10:00:00+05:00",
    decided_by: "Dilnoza Karimova",
    decided_at: "2026-11-01T12:00:00+05:00",
    decision_note: "",
    disputed_at: null,
    dispute_text: "",
    dispute_answer: "",
    dispute_answered_at: null,
    dispute_open: false,
    locked: false,
    payslip: null,
    ...extra,
  };
}

function payslipRow(extra: Partial<PayslipRow> = {}): PayslipRow {
  return {
    id: 6,
    member: { id: 7, name: "Alisher Valiyev", photo_url: null, position: "Farmatsevt", home_branch: "Chilonzor", status: "approved" },
    period: "2026-10-01",
    pay_type: "monthly",
    currency: "UZS",
    base_pay: "4800000.00",
    bonuses: "781990.00",
    fines: "0.00",
    advances: "0.00",
    reimbursements: "0.00",
    gross: "5826000.00",
    deductions: "0.00",
    net: "5826000.00",
    status: "paid",
    published_at: "2026-11-02T16:47:00+05:00",
    viewed_at: "2026-11-02T17:00:00+05:00",
    paid_at: "2026-11-02T17:47:00+05:00",
    received_at: null,
    payout_method: "card",
    ...extra,
  };
}

function payslip(extra: Partial<Payslip> = {}): Payslip {
  return {
    ...payslipRow(),
    run: 1,
    run_status: "paid",
    month: "October 2026",
    scheduled_days: "18.0",
    paid_days: "18.0",
    paid_leave_days: "0.0",
    unpaid_leave_days: "0.0",
    absent_days: "0.0",
    worked_minutes: 12119,
    overtime_minutes: 180,
    night_minutes: 0,
    late_arrivals: 0,
    task_stats: {},
    taxes: {},
    lines: [
      { id: 1, kind: "base", label: "Monthly pay", quantity: null, rate: null, amount: "4800000.00", params: {}, adjustment: null, advance: null, manual: false },
      { id: 2, kind: "fine", label: "Fine: cash shortage", quantity: null, rate: null, amount: "-100000.00", params: {}, adjustment: 11, advance: null, manual: false },
      { id: 3, kind: "rounding", label: "Rounding", quantity: null, rate: null, amount: "-10.00", params: {}, adjustment: null, advance: null, manual: false },
    ],
    ...extra,
  };
}

function advance(extra: Partial<Advance> = {}): Advance {
  return {
    id: 2,
    member: { id: 7, name: "Alisher Valiyev", photo_url: null },
    amount: "1000000.00",
    currency: "UZS",
    installments: 2,
    first_period: "2026-11-01",
    reason: "Rent",
    status: "paid",
    requested_by: "Alisher Valiyev",
    created_at: "2026-10-28T10:00:00+05:00",
    decided_by: "Dilnoza Karimova",
    decided_at: "2026-10-28T12:00:00+05:00",
    decision_note: "",
    paid_at: "2026-10-29T10:00:00+05:00",
    paid_by: "Dilnoza Karimova",
    payout_method: "card",
    repaid: "500000.00",
    left: "500000.00",
    repayments: [{ id: 1, amount: "500000.00", paid_on: "2026-11-30", note: "", payslip: 9, how: "payslip" }],
    debt: 4,
    ...extra,
  };
}

const advances = (extra: Partial<MyAdvances> = {}): MyAdvances => ({
  cap: { currency: "UZS", percent: 50, cap: "2600000.00", used: "1000000.00", available: "1600000.00" },
  advances: [advance()],
  ...extra,
});

const progress = (extra: Partial<Progress> = {}): Progress => ({
  rule: 1,
  name: "On time",
  metric: "tasks.on_time_percent",
  value: "93.00",
  earned: "0.00",
  target: "95.00",
  target_amount: "300000.00",
  min_tasks: 10,
  tasks: 40,
  ...extra,
});

/** The wallet's endpoints as an ordinary month answers them; a test overrides what it is about. */
const DEFAULTS = (): Record<string, unknown> => ({ "/earnings/current/": earnings(), "/payslips/": [], "/adjustments/": [], "/advances/": advances() });

/** Answer the API by path (and method): a value, a function of the body, or an error to throw. */
function serve(overrides: Record<string, unknown>) {
  const routes = { ...DEFAULTS(), ...overrides };
  client.api.mockImplementation(async (path: string, options?: { method?: string; json?: unknown }) => {
    const method = options?.method ?? (options?.json !== undefined ? "POST" : "GET");
    // The longest suffix wins, so "/payslips/6/" isn't answered by "/payslips/".
    const key = Object.keys(routes)
      .filter((route) => {
        const [verb, suffix] = route.includes(" ") ? route.split(" ") : ["GET", route];
        return verb === method && path.endsWith(suffix);
      })
      .sort((a, b) => b.length - a.length)[0];
    if (!key) return {};
    const answer = routes[key];
    if (answer instanceof Error) throw answer;
    return typeof answer === "function" ? (answer as (body: unknown) => unknown)(options?.json) : answer;
  });
}

afterEach(() => {
  cleanup();
  client.api.mockReset();
});

describe("the month so far", () => {
  it("is this month's net so far with the estimate, and nothing without a pay setup", () => {
    expect(homePay(earnings())).toEqual({ amount: "3450000.00", estimate: "5200000.00", currency: "UZS", period: "2026-11-01" });
    expect(homePay(earnings({ has_pay_setup: false }))).toBeNull();
    expect(homePay(undefined)).toBeNull();
    // At the month's end "so far" is the estimate: one number, not two.
    expect(homePay(earnings({ so_far: sums("5200000.00"), estimate: sums("5200000.00") }))?.estimate).toBeNull();
  });

  it("lists base pay always and the other parts only when there are some, in order", () => {
    expect(partRows(sums("0.00", { advances: "-650000.00", bonuses: "120000.00" }))).toEqual([
      { part: "base", amount: "650000.00" },
      { part: "bonuses", amount: "120000.00" },
      { part: "advances", amount: "-650000.00" },
    ]);
    expect(partRows(sums("0.00", { base: "0.00" })).map((row) => row.part)).toEqual(["base"]);
  });

  it("shows the hero, the estimate and the parts, so far or for the whole month", async () => {
    serve({ "/earnings/current/": earnings({ so_far: sums("0.00", { advances: "-650000.00" }), estimate: sums("4200000.00", { base: "5200000.00", advances: "-1000000.00" }) }) });
    renderApp(<WalletPage />, { me });
    expect(await screen.findByText("Net pay so far")).toBeTruthy();
    expect(screen.getByText("Estimate for the month: 4,200,000 UZS")).toBeTruthy();
    expect(screen.getByText("Advance repaid")).toBeTruthy();
    expect(screen.getByText("−650,000 UZS")).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: "Whole month" }));
    expect(screen.getByText("−1,000,000 UZS")).toBeTruthy();
  });

  it("says once that the page didn't open, with one Try again for every part", async () => {
    serve({ "/earnings/current/": new ApiError(500, null), "/payslips/": [], "/adjustments/": [], "/advances/": advances() });
    renderApp(<WalletPage />, { me });
    expect(await screen.findByText("Try again")).toBeTruthy();
    expect(screen.queryByText("Payslips")).toBeNull();
    const asked = client.api.mock.calls.filter(([path]) => String(path).endsWith("/earnings/current/")).length;
    fireEvent.click(screen.getByText("Try again"));
    await waitFor(() => expect(client.api.mock.calls.filter(([path]) => String(path).endsWith("/earnings/current/")).length).toBe(asked + 1));
  });

  it("explains a missing pay setup and leaves out the empty sections", async () => {
    serve({ "/earnings/current/": earnings({ has_pay_setup: false }), "/payslips/": [], "/adjustments/": [], "/advances/": advances({ advances: [] }) });
    renderApp(<WalletPage />, { me });
    expect(await screen.findByText("Your pay isn’t set up yet")).toBeTruthy();
    await waitFor(() => expect(client.api.mock.calls.length).toBeGreaterThanOrEqual(4));
    expect(screen.queryByText("Bonuses and fines")).toBeNull();
    expect(screen.queryByText("You can ask for now")).toBeNull();
  });
});

describe("payslips", () => {
  it("know their state: new, not paid yet, paid and waiting for I received it, received", () => {
    expect(payslipState({ status: "published", viewed_at: null, received_at: null })).toBe("new");
    expect(payslipState({ status: "published", viewed_at: "2026-11-02T10:00:00Z", received_at: null })).toBe("unpaid");
    expect(payslipState({ status: "paid", viewed_at: null, received_at: null })).toBe("confirm");
    expect(payslipState({ status: "paid", viewed_at: null, received_at: "2026-11-02T10:00:00Z" })).toBe("received");
  });

  it("ask on Home about pay to confirm before a new one, and count both for Me's bubble", () => {
    const fresh = payslipRow({ id: 9, period: "2026-11-01", status: "published", viewed_at: null, paid_at: null });
    const paid = payslipRow({ id: 6 });
    const done = payslipRow({ id: 3, period: "2026-09-01", received_at: "2026-10-03T10:00:00Z" });
    expect(payslipToAsk([fresh, paid, done])).toEqual({ row: paid, state: "confirm" });
    expect(payslipToAsk([fresh, done])).toEqual({ row: fresh, state: "new" });
    expect(payslipToAsk([done])).toBeNull();
    expect(payslipsToSee([fresh, paid, done])).toBe(2);
  });

  it("shows every line, and I received it marks a paid one received", async () => {
    let sent = 0;
    serve({
      "/payslips/6/": payslip(),
      "POST /payslips/6/received/": () => {
        sent += 1;
        return payslip({ received_at: "2026-11-02T19:00:00+05:00" });
      },
    });
    const { client: cache } = renderApp(<PayslipPage params={{ id: 6 }} />, {
      me,
      seed: (queries) => queries.setQueryData(walletKeys.payslips(1), [payslipRow()]),
    });
    expect(await screen.findByText("Fine: cash shortage")).toBeTruthy();
    expect(screen.getByText("Did the money reach you?")).toBeTruthy();
    expect(screen.getByText("Paid: 2 November · to a card")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "I received it" }));
    expect(await screen.findByText("You received it: 2 November")).toBeTruthy();
    expect(sent).toBe(1);
    expect(screen.queryByRole("button", { name: "I received it" })).toBeNull();
    // The list's copy follows, so Home's card and Me's bubble let go at once.
    expect(cache.getQueryData<PayslipRow[]>(walletKeys.payslips(1))?.[0].received_at).toBe("2026-11-02T19:00:00+05:00");
  });

  it("has nothing to confirm before it is paid, and nothing more once received", async () => {
    serve({ "/payslips/6/": payslip({ status: "published", paid_at: null }) });
    renderApp(<PayslipPage params={{ id: 6 }} />, { me });
    expect(await screen.findByText("Not paid yet")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "I received it" })).toBeNull();
  });

  it("says the page isn't here for a payslip that isn't mine", async () => {
    serve({ "/payslips/99/": new ApiError(404, { detail: "Not found." }) });
    renderApp(<PayslipPage params={{ id: 99 }} />, { me });
    expect(await screen.findByText("This page isn't here")).toBeTruthy();
  });
});

describe("bonuses and fines", () => {
  it("can be disputed once: a fine or deduction that stands on an open month", () => {
    expect(canDispute(adjustment())).toBe(true);
    expect(canDispute(adjustment({ status: "proposed" }))).toBe(true);
    expect(canDispute(adjustment({ kind: "bonus" }))).toBe(false);
    expect(canDispute(adjustment({ status: "void" }))).toBe(false);
    expect(canDispute(adjustment({ locked: true }))).toBe(false);
    expect(canDispute(adjustment({ disputed_at: "2026-11-02T10:00:00Z" }))).toBe(false);
    expect(disputeStage(adjustment({ disputed_at: "2026-11-02T10:00:00Z" }))).toBe("waiting");
    expect(disputeStage(adjustment({ disputed_at: "2026-11-02T10:00:00Z", dispute_answered_at: "2026-11-03T10:00:00Z" }))).toBe("answered");
    expect(disputeStage(adjustment({ kind: "bonus" }))).toBe("none");
  });

  it("send the dispute's text trimmed, and nothing empty or too long", () => {
    expect(disputePayload("  I had no shift that day ")).toEqual({ text: "I had no shift that day" });
    expect(disputePayload("   ")).toBeNull();
    expect(disputePayload("x".repeat(501))).toBeNull();
  });

  it("group by month, newest first", () => {
    const rows = [adjustment({ id: 1 }), adjustment({ id: 2 }), adjustment({ id: 3, period: "2026-10-01" })];
    expect(byMonth(rows).map((group) => [group.period, group.rows.map((row) => row.id)])).toEqual([
      ["2026-11-01", [1, 2]],
      ["2026-10-01", [3]],
    ]);
  });

  it("dispute a fine from its sheet and then wait for the answer", async () => {
    const bodies: unknown[] = [];
    let row = adjustment();
    serve({
      "/adjustments/": () => [row],
      "POST /adjustments/11/dispute/": (body: unknown) => {
        bodies.push(body);
        row = adjustment({ disputed_at: "2026-11-02T18:00:00+05:00", dispute_text: "I had no shift that day", dispute_open: true });
        return row;
      },
    });
    renderApp(<AdjustmentSheet params={{ id: 11 }} close={() => undefined} />, { me });
    fireEvent.click(await screen.findByRole("button", { name: "Dispute it" }));
    const send = screen.getByRole("button", { name: "Send" }) as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Why do you disagree?"), { target: { value: "  I had no shift that day  " } });
    fireEvent.click(send);
    expect(await screen.findByText("Waiting for an answer")).toBeTruthy();
    expect(bodies).toEqual([{ text: "I had no shift that day" }]);
    expect(screen.queryByRole("button", { name: "Dispute it" })).toBeNull();
  });

  it("show the answer to a dispute, and say why a closed month can't be disputed", async () => {
    serve({
      "/adjustments/": [
        adjustment({ disputed_at: "2026-11-02T10:00:00+05:00", dispute_text: "Terminal error", dispute_answered_at: "2026-11-03T10:00:00+05:00", dispute_answer: "Checked: it was the terminal. Taken back." }),
        adjustment({ id: 12, locked: true, payslip: 6, period: "2026-10-01" }),
      ],
    });
    renderApp(<AdjustmentSheet params={{ id: 11 }} close={() => undefined} />, { me });
    expect(await screen.findByText("Checked: it was the terminal. Taken back.")).toBeTruthy();
    cleanup();
    renderApp(<AdjustmentSheet params={{ id: 12 }} close={() => undefined} />, { me });
    expect(await screen.findByText("This month is closed, so it can’t be disputed now.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "On the payslip for October 2026" })).toBeTruthy();
  });
});

describe("advances", () => {
  const cap = { available: "1600000.00" };

  it("check the request against the cap the server gives, and send it in the server's form", () => {
    expect(advanceDraft({ typing: "", installments: 1, reason: "" }, cap)).toEqual({ problem: "empty" });
    expect(advanceDraft({ typing: "0", installments: 1, reason: "" }, cap)).toEqual({ problem: "zero" });
    expect(advanceDraft({ typing: "1600001", installments: 1, reason: "" }, cap)).toEqual({ problem: "overCap" });
    expect(advanceDraft({ typing: "500000", installments: 1, reason: "x".repeat(301) }, cap)).toEqual({ problem: "reasonTooLong" });
    expect(advanceDraft({ typing: "500000", installments: 1, reason: "" }, { available: "0.00" })).toEqual({ problem: "noRoom" });
    expect(advanceDraft({ typing: "1600000", installments: 2, reason: "  Rent " }, cap)).toEqual({
      payload: { amount: "1600000.00", installments: 2, reason: "Rent" },
    });
    expect(advanceDraft({ typing: "500000", installments: 40, reason: "" }, cap)).toEqual({ payload: { amount: "500000.00", installments: 12, reason: "" } });
  });

  it("come off the pay month by month, the repaid ones ticked", () => {
    expect(addMonths("2026-11-01", 2)).toBe("2027-01-01");
    expect(repaymentMonths(advance())).toEqual([
      { period: "2026-11-01", repayment: advance().repayments[0], done: true },
      { period: "2026-12-01", repayment: null, done: false },
    ]);
    expect(repaymentMonths(advance({ status: "repaid", repayments: [] })).every((month) => month.done)).toBe(true);
  });

  it("ask for one from the sheet: over the cap it says so, within it sends amount, months and reason", async () => {
    const bodies: unknown[] = [];
    const closed = vi.fn();
    serve({ "/advances/": advances(), "POST /advances/": (body: unknown) => (bodies.push(body), advance({ status: "requested" })) });
    renderApp(<AdvanceRequestSheet params={{}} close={closed} />, { me });
    const amount = await screen.findByLabelText("Amount");
    fireEvent.change(amount, { target: { value: "2000000" } });
    expect(screen.getByText("You can ask for 1,600,000 UZS at most")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Ask for an advance" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(amount, { target: { value: "500000" } });
    fireEvent.click(screen.getByRole("button", { name: "2 months" }));
    fireEvent.change(screen.getByLabelText(/Reason/), { target: { value: "Rent" } });
    fireEvent.click(screen.getByRole("button", { name: /^Ask for 500,000\sUZS$/ }));
    await waitFor(() => expect(closed).toHaveBeenCalled());
    expect(bodies).toEqual([{ amount: "500000.00", installments: 2, reason: "Rent" }]);
  });

  it("can be taken back while nobody has decided", async () => {
    const confirmed = vi.spyOn(window, "confirm").mockReturnValue(true);
    let cancelled = 0;
    serve({ "/advances/": advances({ advances: [advance({ status: "requested", repayments: [], paid_at: null, decided_by: null })] }), "POST /advances/2/cancel/": () => ((cancelled += 1), advance({ status: "cancelled" })) });
    const closed = vi.fn();
    renderApp(<AdvanceSheet params={{ id: 2 }} close={closed} />, { me });
    fireEvent.click(await screen.findByRole("button", { name: "Cancel the request" }));
    await waitFor(() => expect(closed).toHaveBeenCalled());
    expect(cancelled).toBe(1);
    confirmed.mockRestore();
  });
});

describe("bonus rules' progress", () => {
  it("shows the next step of a more-is-better rule with its bar", () => {
    const view = progressView(progress());
    expect(view.caption).toEqual({ key: "progress.next", target: "95.00", amount: "300000.00" });
    expect(view.bar).toEqual({ value: 93, total: 95 });
  });

  it("counts what is left of an at-most rule that pays now: 2 kechikish qoldi — bonus saqlanadi", () => {
    const late = (extra: Partial<Progress>) => progressView(progress({ metric: "attendance.late_arrivals", value: "0.00", earned: "200000.00", target: null, target_amount: null, min_tasks: null, tasks: null, op: "lte", limit: "2.00", ...extra }));
    expect(late({}).caption).toEqual({ key: "progress.keepLate", count: 2 });
    expect(late({ op: "lt", limit: "3.00" }).caption).toEqual({ key: "progress.keepLate", count: 2 });
    expect(late({ value: "2.00" }).caption).toEqual({ key: "progress.keepLast" });
    expect(late({ metric: "attendance.absences", value: "1.00" }).caption).toEqual({ key: "progress.keepLeft", count: 1 });
    expect(late({ metric: "attendance.late_minutes", value: "12.00", limit: "30.00" }).caption).toEqual({ key: "progress.keepMinutes", count: 18 });
    expect(late({ metric: "tasks.reminders_per_task", value: "0.50", limit: "1.50" }).caption).toEqual({ key: "progress.keepLimit", limit: "1.50" });
    // An older server without op and limit: the metric tells the direction, nothing is made up.
    expect(late({ op: undefined, limit: undefined }).caption).toEqual({ key: "progress.kept" });
    expect(late({}).good).toBe(true);
    expect(late({}).bar).toBeNull();
  });

  it("says what was earned, what isn't yet, and when there are too few tasks to judge", () => {
    expect(progressView(progress({ earned: "300000.00", target: null, target_amount: null })).caption).toEqual({ key: "progress.earned", amount: "300000.00" });
    expect(progressView(progress({ metric: "sales.net", value: "0.00", target: "0.00", target_amount: null })).caption).toEqual({ key: "progress.none" });
    expect(progressView(progress({ tasks: 4 })).caption).toEqual({ key: "progress.minTasks", min: 10, count: 4 });
    expect(progressView(progress({ metric: "attendance.late_arrivals", value: "4.00", target: "2.00", target_amount: "100000.00", op: "lte" })).caption).toEqual({
      key: "progress.atMost",
      target: "2.00",
      amount: "100000.00",
    });
  });

  it("writes metric numbers the way people read them", () => {
    expect(plainNumber("90.30", "uz")).toBe("90,3");
    expect(plainNumber("1250.00", "en")).toBe("1,250");
    expect(plainNumber("2.00", "ru")).toBe("2");
  });

  it("render on the wallet in the brief's words", async () => {
    serve({
      "/earnings/current/": earnings({ progress: [progress({ name: "Punctual", metric: "attendance.late_arrivals", value: "0.00", earned: "200000.00", target: null, target_amount: null, op: "lte", limit: "2.00" })] }),
    });
    renderApp(<WalletPage />, { me, lang: "uz" });
    expect(await screen.findByText("2 ta kechikish qoldi — bonus saqlanadi")).toBeTruthy();
    expect(screen.getByText("Kechikib kelishlar")).toBeTruthy();
  });
});

describe("Home and Me", () => {
  it("Home's card says the month so far in the brief's words, and nothing without a pay setup", async () => {
    serve({ "/earnings/current/": earnings() });
    renderApp(<MonthCard member={member} summary={undefined} />, { me, lang: "uz" });
    expect(await screen.findByText("Bu oy: 3 450 000 so‘m hozircha")).toBeTruthy();
    expect(screen.getByText("Oy uchun taxmin: 5 200 000 so‘m")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Bu oy/ }));
    expect(navigationState().stack).toEqual([{ feature: "wallet", page: "home" }]);
    cleanup();
    serve({ "/earnings/current/": earnings({ has_pay_setup: false }) });
    const { container } = renderApp(<MonthCard member={member} summary={undefined} />, { me });
    await waitFor(() => expect(client.api).toHaveBeenCalled());
    await act(async () => undefined);
    expect(container.querySelector(".banner")).toBeNull();
  });

  it("Home asks about pay that went out, and opens that payslip", async () => {
    serve({ "/payslips/": [payslipRow()] });
    renderApp(<PayslipCard member={member} summary={undefined} />, { me });
    fireEvent.click(await screen.findByText("October 2026: your pay is out"));
    expect(navigationState().stack).toEqual([{ feature: "wallet", page: "payslip", params: { id: 6 } }]);
  });

  it("Me's row shows the month so far, short, with a bubble for payslips to see", async () => {
    serve({ "/earnings/current/": earnings(), "/payslips/": [payslipRow()] });
    const item = wallet.meItems![0];
    function Row() {
      const status = item.useStatus!({ member, summary: undefined });
      return (
        <div data-testid="status">
          {String(status.value)}|{String(status.badge)}
        </div>
      );
    }
    renderApp(<Row />, { me });
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("3.5M UZS|1"));
  });

  it("is on with the company's payroll, for approved and suspended people", () => {
    const visible = (fields: object) => featureVisible(wallet, { member: { ...member, ...fields } as never, summary: undefined });
    expect(visible({})).toBe(true);
    expect(visible({ status: "suspended" })).toBe(true);
    expect(visible({ status: "pending" })).toBe(false);
    expect(visible({ company: { ...company, features: ["hr"] } })).toBe(false);
  });
});

describe("deep links from the bot", () => {
  it("open the wallet and a payslip over Me", () => {
    expect(resolveScreen({ name: "wallet", arg: null }, features)).toEqual({ tab: "profile", stack: [{ feature: "wallet", page: "home", params: {} }] });
    expect(resolveScreen({ name: "pay", arg: null }, features)).toEqual({ tab: "profile", stack: [{ feature: "wallet", page: "home", params: {} }] });
    expect(resolveScreen({ name: "payslip", arg: "12" }, features)).toEqual({ tab: "profile", stack: [{ feature: "wallet", page: "payslip", params: { id: 12 } }] });
    expect(resolveScreen({ name: "wallet.advances", arg: null }, features)).toEqual({ tab: "home", stack: [{ feature: "wallet", page: "advances", params: {} }] });
  });

  it("a payslip link renders the payslip page through the registry", async () => {
    serve({ "/payslips/12/": payslip({ id: 12 }) });
    const init = resolveScreen({ name: "payslip", arg: "12" }, features)!;
    const Page = wallet.pages!.payslip!;
    renderApp(<Page params={init.stack![0].params!} />, { me, init });
    expect(await screen.findByText("How it adds up")).toBeTruthy();
    expect(within(document.body).getByText("Monthly pay")).toBeTruthy();
  });
});
