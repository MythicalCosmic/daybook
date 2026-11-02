// Payroll screens against a stubbed API: what goes out on mark paid, a bulk decision and the rule
// preview; what a viewer without the right permissions sees (no actions, "Hidden" amounts);
// how a payslip line explains itself; locked pay setups.
// The registry first, as in the app (core/modules loads every module's index.ts).
import "@/core/modules";

import { flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { confirmQueue, settleConfirm } from "@/components/useConfirm";
import type { Perm } from "@/core/perms";
import { mergeModuleMessages } from "@/i18n";
import { useSessionStore } from "@/stores/session";
import { company, json, me } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

import PayAmount from "../components/PayAmount.vue";
import PayHistory from "../components/PayHistory.vue";
import en from "../i18n/en.json";
import { emptyRule, ruleToDraft } from "../lib";
import type { Adjustment, Compensation, Payslip, Rule, Run } from "../types";

// Whole pages mount here: slow while the rest of the suite runs beside them.
vi.setConfig({ testTimeout: 20_000 });

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

/** Answers `METHOD path` (after /api/v1/owner/companies/1/) and records every call. */
function stub(routes: Record<string, (call: Call) => Response>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal("ResizeObserver", NoResize);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const path = url.replace(/^.*\/api\/v1\/owner\/companies\/1\//, "").split("?")[0]!;
      const call = { method: init?.method ?? "GET", path, body: init?.body ? JSON.parse(String(init.body)) : undefined };
      calls.push(call);
      return routes[`${call.method} ${path}`]?.(call) ?? json({ detail: "Not found." }, 404);
    }),
  );
  return calls;
}

const page = <T>(results: T[]) => ({ count: results.length, next: null, previous: null, results });

/** Signs the test in as a non-owner holding these permissions in company 1. */
function as(permissions: Perm[]): void {
  useSessionStore().me = me([company({ is_owner: false, permissions })]);
}

async function settle(): Promise<void> {
  for (let i = 0; i < 4; i += 1) await flushPromises();
}

beforeEach(() => {
  mergeModuleMessages("payroll", { en, ru: en, uz: en });
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  confirmQueue.value = [];
  document.body.innerHTML = "";
});

const run = (overrides: Partial<Run> = {}): Run => ({
  id: 7,
  period: "2026-10-01",
  kind: "regular",
  status: "finalized",
  member: null,
  usd_rate: null,
  calculated_at: "2026-11-01T06:00:00+05:00",
  finalized_at: "2026-11-01T09:00:00+05:00",
  finalized_by: "Dilnoza Karimova",
  paid_at: null,
  notes: "",
  warnings: [],
  totals: { currency: "UZS", people: 3, gross: "15300000.00", deductions: "550000.00", net: "14750000.75", paid: 0, published: 3 },
  ...overrides,
});

const slip = (id: number, overrides: Partial<Payslip> = {}): Payslip => ({
  id,
  run: 7,
  period: "2026-10-01",
  member: { id: id * 10, name: `Farmatsevt ${id}` },
  currency: "UZS",
  pay_type: "monthly",
  base_pay: "4800000.00",
  scheduled_days: "26.0",
  paid_days: "24.0",
  net: "4550000.25",
  status: "published",
  published_at: null,
  viewed_at: null,
  paid_at: null,
  payout_method: "",
  received_at: null,
  ...overrides,
});

const adjustment = (id: number, overrides: Partial<Adjustment> = {}): Adjustment => ({
  id,
  member: { id: 3, name: "Alisher Valiyev", photo_url: null },
  period: "2026-11-01",
  kind: "fine",
  amount: "60000.00",
  currency: "UZS",
  reason: "Late five times, two free",
  source: "manual",
  rule: null,
  task: null,
  status: "proposed",
  proposed_by: "Bekzod Mirzayev",
  decided_by: null,
  decided_at: null,
  disputed_at: null,
  dispute_text: "",
  dispute_answer: "",
  payslip: null,
  created_at: "2026-11-02T10:00:00+05:00",
  ...overrides,
});

describe("mark paid", () => {
  it("sends the payslips still waiting, the method and the account, and shows their exact total", async () => {
    const calls = stub({
      "GET finance/options/": () => json({ accounts: [{ id: 3, name: "Kassa", kind: "cash", currency: "UZS" }, { id: 4, name: "Kapitalbank", kind: "bank", currency: "UZS" }] }),
      "POST payroll/runs/7/mark-paid/": () => json(run({ status: "paid" })),
    });
    const MarkPaidDialog = (await import("../components/MarkPaidDialog.vue")).default;
    const app = await testApp("/c/1/payroll/runs/7");
    const slips = [slip(1), slip(2, { net: "5200000.50" }), slip(3, { status: "paid" })];
    mountWithProviders(MarkPaidDialog, { plugins: app.plugins, props: { open: true, run: run(), payslips: slips } });
    await settle();
    // 4 550 000,25 + 5 200 000,50, added exactly; the paid one isn't offered.
    expect(document.querySelector('[data-testid="pay-total"]')?.textContent).toContain("9,750,000.75");
    expect(document.body.textContent).not.toContain("Farmatsevt 3");
    (document.querySelector('[data-testid="mark-paid-confirm"]') as HTMLButtonElement).click();
    await settle();
    const post = calls.find((call) => call.method === "POST");
    expect(post).toEqual({ method: "POST", path: "payroll/runs/7/mark-paid/", body: { payslip_ids: [1, 2], method: "cash", account: 3 } });
  });
});

describe("mark paid refused", () => {
  it("says the server's reason inside the dialog (a toast would sit behind it)", async () => {
    stub({
      "GET finance/options/": () => json({ accounts: [{ id: 10, name: "Biznes karta", kind: "card", currency: "UZS" }] }),
      "POST payroll/runs/7/mark-paid/": () => json({ detail: "Not enough money in Biznes karta: 3 686 000 left." }, 400),
    });
    const MarkPaidDialog = (await import("../components/MarkPaidDialog.vue")).default;
    const app = await testApp("/c/1/payroll/runs/7");
    mountWithProviders(MarkPaidDialog, { plugins: app.plugins, props: { open: true, run: run(), payslips: [slip(1)] } });
    await settle();
    (document.querySelector('[data-testid="mark-paid-confirm"]') as HTMLButtonElement).click();
    await settle();
    expect(document.querySelector('[data-testid="pay-failure"]')?.textContent).toContain("Not enough money in Biznes karta");
    // Still open, to choose another account.
    expect(document.querySelector('[data-testid="mark-paid-confirm"]')).not.toBeNull();
  });
});

describe("bonuses and fines", () => {
  it("bulk approval sends only the proposed rows, with approve and no reason", async () => {
    const rows = [adjustment(41), adjustment(42, { kind: "bonus", amount: "300000.00" })];
    const calls = stub({
      "GET payroll/adjustments/": () => json(page(rows)),
      "POST payroll/adjustments/bulk-decide/": () => json([{ id: 41, ok: true, status: "approved" }, { id: 42, ok: true, status: "approved" }]),
    });
    const AdjustmentsPage = (await import("../pages/AdjustmentsPage.vue")).default;
    const app = await testApp("/c/1/payroll/adjustments");
    mountWithProviders(AdjustmentsPage, { plugins: app.plugins });
    await settle();
    (document.querySelector("thead [role=checkbox]") as HTMLElement).click();
    await settle();
    (document.querySelector('[data-testid="bulk-approve"]') as HTMLButtonElement).click();
    await settle();
    expect(confirmQueue.value).toHaveLength(1);
    settleConfirm(confirmQueue.value[0]!.id, { reason: "" }, 0);
    await settle();
    expect(calls.find((call) => call.path === "payroll/adjustments/bulk-decide/")?.body).toEqual({ ids: [41, 42], approve: true });
  });

  it("a proposer without payroll.view sees 'Hidden' for the amount and no approve buttons", async () => {
    stub({ "GET payroll/adjustments/": () => json(page([adjustment(41, { amount: undefined })])) });
    const AdjustmentsPage = (await import("../pages/AdjustmentsPage.vue")).default;
    const app = await testApp("/c/1/payroll/adjustments");
    as(["payroll.propose", "dashboard.access"]);
    mountWithProviders(AdjustmentsPage, { plugins: app.plugins });
    await settle();
    const amount = document.querySelector("[data-hidden-amount]");
    expect(amount?.textContent).toContain(en["payroll.hidden"]);
    expect(document.querySelector("tbody")?.textContent).not.toMatch(/\b0\s*UZS/);
    expect(document.querySelector('[data-testid="bulk-approve"]')).toBeNull();
    expect(document.querySelector("thead [role=checkbox]")).toBeNull();
    // They may still propose.
    expect(document.querySelector('[data-testid="new-bonus"]')).not.toBeNull();
  });
});

describe("runs", () => {
  /** The test app with the run page's own route, so `:runId` is a param as in the app. */
  async function runApp() {
    const app = await testApp("/c/1/payroll");
    app.router.addRoute({ path: "/c/:companyId/payroll/runs/:runId(\\d+)", component: { render: () => null } });
    await app.router.replace("/c/1/payroll/runs/7");
    return app;
  }

  it("a viewer sees the run but none of its actions; the owner gets Finalize and Recalculate", async () => {
    const draft = run({ status: "draft", finalized_at: null, finalized_by: null });
    const routes = { "GET payroll/runs/7/": () => json(draft), "GET payroll/runs/7/payslips/": () => json(page([slip(1, { status: "draft" })])) };
    const RunPage = (await import("../pages/RunPage.vue")).default;

    stub(routes);
    let app = await runApp();
    as(["payroll.view", "dashboard.access"]);
    let mounted = mountWithProviders(RunPage, { plugins: app.plugins });
    await settle();
    expect(document.body.textContent).toContain("Farmatsevt 1");
    expect(document.querySelector('[data-testid^="run-"]:not([data-testid="run-totals"]):not([data-testid="run-net"])')).toBeNull();
    mounted.wrapper.unmount();
    document.body.innerHTML = "";

    stub(routes);
    app = await runApp();
    mounted = mountWithProviders(RunPage, { plugins: app.plugins });
    await settle();
    expect(document.querySelector('[data-testid="run-finalize"]')).not.toBeNull();
    expect(document.querySelector('[data-testid="run-calculate"]')).not.toBeNull();
    mounted.wrapper.unmount();
  });

  it("finalizing asks first, then calls finalize", async () => {
    const draft = run({ status: "draft", finalized_at: null, finalized_by: null });
    const calls = stub({
      "GET payroll/runs/7/": () => json(draft),
      "GET payroll/runs/7/payslips/": () => json(page([slip(1, { status: "draft" })])),
      "POST payroll/runs/7/finalize/": () => json(run()),
    });
    const RunPage = (await import("../pages/RunPage.vue")).default;
    const app = await runApp();
    mountWithProviders(RunPage, { plugins: app.plugins });
    await settle();
    (document.querySelector('[data-testid="run-finalize"]') as HTMLButtonElement).click();
    await settle();
    expect(calls.some((call) => call.path.endsWith("finalize/"))).toBe(false);
    settleConfirm(confirmQueue.value[0]!.id, { reason: "" }, 0);
    await settle();
    expect(calls.filter((call) => call.method === "POST").map((call) => call.path)).toEqual(["payroll/runs/7/finalize/"]);
  });

  it("the payslip drawer shows every line with how it was worked out", async () => {
    const detail = slip(1, {
      gross: "5100000.00",
      deductions: "550000.00",
      net: "4550000.00",
      lines: [
        { id: 1, kind: "base", label: "Base pay: 24 of 26 days", params: {}, quantity: "24.0", rate: "200000.00", amount: "4800000.00", adjustment: null, advance: null, order: 1 },
        { id: 2, kind: "bonus", label: "Bonus: best sales", params: {}, quantity: null, rate: null, amount: "300000.00", adjustment: 44, advance: null, order: 2 },
        { id: 3, kind: "advance", label: "Advance repayment", params: {}, quantity: null, rate: null, amount: "-500000.00", adjustment: null, advance: 64, order: 3 },
      ],
    });
    stub({ "GET payroll/payslips/1/": () => json(detail) });
    const PayslipDrawer = (await import("../components/PayslipDrawer.vue")).default;
    const app = await testApp("/c/1/payroll/runs/7?payslip=1");
    await app.router.replace("/c/1/payroll/runs/7?payslip=1");
    mountWithProviders(PayslipDrawer, { plugins: app.plugins, props: { run: run() } });
    await settle();
    const lines = document.querySelector('[data-testid="payslip-lines"]')?.textContent ?? "";
    expect(lines).toContain("Base pay: 24 of 26 days");
    expect(lines).toContain("24 × 200,000\u00a0UZS");
    expect(lines).toContain("−500,000\u00a0UZS");
    expect(document.querySelector('[data-testid="payslip-net"]')?.textContent).toContain("4,550,000\u00a0UZS");
  });
});

describe("rule preview", () => {
  const saved: Rule = {
    id: 5,
    name: "Late arrivals",
    kind: "fine",
    metric: "attendance.late_arrivals",
    mode: "per_unit",
    op: "gte",
    threshold: null,
    free_units: "2.00",
    tiers: [],
    amount_type: "fixed",
    amount: "20000.00",
    cap: null,
    min_tasks: 10,
    positions: [],
    evaluate: "monthly",
    auto_approve: false,
    is_active: false,
    example: true,
    created_at: "2026-11-01T09:00:00Z",
    updated_at: "2026-11-01T09:00:00Z",
  };
  const answer = {
    period: "2026-10-01",
    to: "2026-10-31",
    currency: "UZS",
    total: "40000.00",
    rows: [
      { member: { id: 2, name: "Aziza Rasulova", photo_url: null }, value: "1", amount: null, units: null, tier: null },
      { member: { id: 3, name: "Bobur Saidov", photo_url: null }, value: "4", amount: "40000.00", units: "2", tier: null },
    ],
  };

  it("dry-runs the saved rule for last month and shows who it fines, the rest folded", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"], now: new Date("2026-11-02T12:00:00+05:00") });
    try {
      const calls = stub({ "POST payroll/rules/5/preview/": () => json(answer) });
      const RulePreview = (await import("../components/RulePreview.vue")).default;
      const app = await testApp("/c/1/payroll/rules?rule=5");
      mountWithProviders(RulePreview, { plugins: app.plugins, props: { draft: ruleToDraft(saved), rule: saved } });
      await vi.advanceTimersByTimeAsync(100);
      await settle();
      // Only the month goes: the server runs the rule as saved.
      expect(calls.find((call) => call.path === "payroll/rules/5/preview/")?.body).toEqual({ period: "2026-10-01" });
      expect(document.querySelector('[data-testid="preview-total"]')?.textContent).toContain("−40,000 UZS");
      const rows = document.querySelector('[data-testid="preview-rows"]')?.textContent ?? "";
      expect(rows).toContain("Bobur Saidov");
      expect(rows).toContain("Counted: 2");
      expect(rows).not.toContain("Aziza");
      expect(document.querySelector('[data-testid="preview-others"]')?.textContent).toContain("Not matched: 1");
      expect(document.querySelector('[data-testid="preview-saved-only"]')).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("says it shows the saved rule while the form has changes", async () => {
    stub({ "POST payroll/rules/5/preview/": () => json(answer) });
    const RulePreview = (await import("../components/RulePreview.vue")).default;
    const app = await testApp("/c/1/payroll/rules?rule=5");
    mountWithProviders(RulePreview, { plugins: app.plugins, props: { draft: { ...ruleToDraft(saved), amount: "25000.00" }, rule: saved } });
    await settle();
    expect(document.querySelector('[data-testid="preview-saved-only"]')).not.toBeNull();
  });

  it("a new rule is saved before it can be tried: nothing is asked", async () => {
    const calls = stub({});
    const RulePreview = (await import("../components/RulePreview.vue")).default;
    const app = await testApp("/c/1/payroll/rules?rule=new");
    mountWithProviders(RulePreview, { plugins: app.plugins, props: { draft: emptyRule("fine"), rule: null } });
    await settle();
    expect(document.querySelector('[data-testid="preview-save-first"]')).not.toBeNull();
    expect(calls.filter((call) => call.path.includes("preview"))).toEqual([]);
  });
});

describe("pay setups", () => {
  const row = (id: number, from: string, overrides: Partial<Compensation> = {}): Compensation => ({
    id,
    member: { id: 3, name: "Alisher Valiyev", photo_url: null },
    effective_from: from,
    pay_type: "monthly",
    amount: "5200000.00",
    currency: "UZS",
    proration: "attendance",
    pays_task_rates: false,
    overtime_eligible: true,
    note: "",
    created_by: "Dilnoza Karimova",
    created_at: `${from}T09:00:00+05:00`,
    locked: false,
    ...overrides,
  });

  it("a locked setup says why and can't be edited; an unused one can", async () => {
    const app = await testApp("/c/1/payroll/pay");
    const history = [row(2, "2026-12-01", { amount: "5600000.00" }), row(1, "2026-03-01", { locked: true, locked_reason: "A finalized payroll used it." })];
    const { wrapper } = mountWithProviders(PayHistory, { plugins: app.plugins, props: { history, current: history[1], editable: true } });
    await settle();
    expect(wrapper.find('[data-testid="pay-locked"]').text()).toContain("A finalized payroll used it.");
    const cards = wrapper.findAll("article");
    expect(cards[0]!.find("button").exists()).toBe(true);
    expect(cards[1]!.find("button").exists()).toBe(false);
    expect(cards[0]!.text()).toContain("5,600,000\u00a0UZS");
  });

  it("a link to someone not on the list says so, with nothing to change", async () => {
    stub({ "GET payroll/compensations/": () => json(page([])) });
    const PayDrawer = (await import("../components/PayDrawer.vue")).default;
    const app = await testApp("/c/1/payroll/pay?member=999");
    mountWithProviders(PayDrawer, { plugins: app.plugins, props: { rows: [], ready: true } });
    await settle();
    expect(document.querySelector('[data-testid="pay-not-found"]')?.textContent).toContain(en["payroll.pay.notFound"]);
    expect(document.querySelector('[data-testid="change-pay"]')).toBeNull();
  });
});

describe("amounts", () => {
  it("print the server's string exactly, and 'Hidden' when it was left out, never 0", async () => {
    const app = await testApp("/c/1/payroll");
    const shown = mountWithProviders(PayAmount, { plugins: app.plugins, props: { value: "4960000.50", currency: "UZS" } });
    expect(shown.wrapper.text()).toBe("4,960,000.50\u00a0UZS");
    const hidden = mountWithProviders(PayAmount, { plugins: app.plugins, props: { value: undefined, currency: "UZS" } });
    expect(hidden.wrapper.text()).toBe(en["payroll.hidden"]);
    expect(hidden.wrapper.text()).not.toContain("0");
  });

  it("a quiet zero is still printed, only dimmed and unsigned; other amounts are untouched", async () => {
    const app = await testApp("/c/1/payroll");
    const zero = mountWithProviders(PayAmount, { plugins: app.plugins, props: { value: "0.00", currency: "UZS", cell: true, quietZero: true, sign: "always", colored: true } });
    expect(zero.wrapper.text()).toContain("0 UZS");
    expect(zero.wrapper.text()).not.toContain("+");
    expect(zero.wrapper.html()).toContain("opacity-40");
    const bonus = mountWithProviders(PayAmount, { plugins: app.plugins, props: { value: "300000.00", currency: "UZS", cell: true, quietZero: true, sign: "always", colored: true } });
    expect(bonus.wrapper.text()).toContain("+300,000 UZS");
    expect(bonus.wrapper.html()).not.toContain("opacity-40");
  });
});
