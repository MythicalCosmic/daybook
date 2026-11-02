// The payroll module's logic (money strings use no-break spaces, as the app prints them): run actions, mark-paid selection, bulk decisions, the rule builder's
// payload and preview request, pay history and locks, amounts the viewer may not see, settings.
import { describe, expect, it } from "vitest";

import { formatMoney } from "@/lib/money";

import {
  accountsFor,
  adaptToMetric,
  bulkOutcome,
  bulkPlan,
  changePlan,
  emptyRule,
  hasAmount,
  lineGroups,
  lineHow,
  monthName,
  payHistory,
  payRowMatches,
  paySelection,
  prepareTarget,
  previewBody,
  quantityText,
  repaidShare,
  ruleInput,
  ruleProblems,
  ruleToDraft,
  runActions,
  settingsChanges,
  settingsForm,
  signedAmount,
  suggestedEffectiveFrom,
  warningLink,
  type Can,
  type RuleDraft,
} from "../lib";
import type { Adjustment, Compensation, PayAccount, PayrollSettings, PayRow, Payslip, PayslipLine, Rule, Run } from "../types";

const all: Can = () => true;
const only =
  (...perms: string[]): Can =>
  (perm) =>
    perms.includes(perm);

function run(overrides: Partial<Run> = {}): Run {
  return {
    id: 7,
    period: "2026-10-01",
    kind: "regular",
    status: "draft",
    member: null,
    usd_rate: null,
    calculated_at: "2026-11-01T06:00:00+05:00",
    finalized_at: null,
    finalized_by: null,
    paid_at: null,
    notes: "",
    warnings: [],
    totals: null,
    ...overrides,
  };
}

function slip(id: number, overrides: Partial<Payslip> = {}): Payslip {
  return {
    id,
    run: 7,
    period: "2026-10-01",
    member: { id: id * 10, name: `Person ${id}` },
    currency: "UZS",
    pay_type: "monthly",
    base_pay: "5200000.00",
    scheduled_days: "26.0",
    paid_days: "26.0",
    net: "5200000.00",
    status: "published",
    published_at: null,
    viewed_at: null,
    paid_at: null,
    payout_method: "",
    received_at: null,
    ...overrides,
  };
}

function comp(id: number, from: string, overrides: Partial<Compensation> = {}): Compensation {
  return {
    id,
    member: { id: 3, name: "Alisher Valiyev" },
    effective_from: from,
    pay_type: "monthly",
    amount: "5200000.00",
    currency: "UZS",
    proration: "attendance",
    pays_task_rates: false,
    overtime_eligible: false,
    note: "",
    created_by: null,
    created_at: `${from}T09:00:00+05:00`,
    locked: false,
    ...overrides,
  };
}

function adjustment(id: number, status: Adjustment["status"]): Adjustment {
  return {
    id,
    member: { id: 3, name: "Alisher Valiyev" },
    period: "2026-11-01",
    kind: "fine",
    amount: "50000.00",
    currency: "UZS",
    reason: "Fridge log not filled in",
    source: "manual",
    rule: null,
    task: null,

    status,
    proposed_by: null,
    decided_by: null,
    decided_at: null,
    disputed_at: null,
    dispute_text: "",
    dispute_answer: "",
    payslip: null,
    created_at: "2026-11-02T10:00:00+05:00",
  };
}

describe("run actions", () => {
  it("a calculated draft can be recalculated, finalized, cancelled and exported", () => {
    expect(runActions(run(), all)).toEqual(["calculate", "finalize", "cancel", "export"]);
  });

  it("a draft never calculated can't be finalized yet", () => {
    expect(runActions(run({ calculated_at: null }), all)).toEqual(["calculate", "cancel"]);
  });

  it("a finalized run sends payslips, takes payments and reopens while nothing is paid", () => {
    expect(runActions(run({ status: "finalized" }), all, [slip(1, { status: "draft" })])).toEqual(["publish", "mark_paid", "reopen", "export"]);
    expect(runActions(run({ status: "finalized" }), all, [slip(1), slip(2, { status: "paid" })])).toEqual(["mark_paid", "export"]);
  });

  it("a paid run only exports; a cancelled one does nothing", () => {
    expect(runActions(run({ status: "paid" }), all)).toEqual(["export"]);
    expect(runActions(run({ status: "cancelled" }), all)).toEqual([]);
  });

  it("each action needs its permission", () => {
    const viewer = only("payroll.view");
    expect(runActions(run(), viewer)).toEqual([]);
    expect(runActions(run(), only("payroll.view", "data.export"))).toEqual(["export"]);
    expect(runActions(run(), only("payroll.manage"))).toEqual(["calculate", "cancel"]);
    expect(runActions(run({ status: "finalized" }), only("payroll.pay"), [slip(1)])).toEqual(["mark_paid"]);
    expect(runActions(run({ status: "finalized" }), only("payroll.finalize"), [slip(1, { status: "draft" })])).toEqual(["publish", "reopen"]);
  });

  it("the server's own list wins, still filtered by permission", () => {
    expect(runActions(run({ actions: ["calculate", "finalize"] }), only("payroll.manage"))).toEqual(["calculate"]);
  });
});

describe("mark paid", () => {
  it("covers only payslips still waiting, and adds their net exactly per currency", () => {
    const slips = [
      slip(1, { net: "4350000.50" }),
      slip(2, { net: "5200000.25" }),
      slip(3, { status: "paid", net: "1.00" }),
      slip(4, { currency: "USD", net: "410.10" }),
      slip(5, { net: "0.10" }),
    ];
    const selection = paySelection(slips, ["1", "2", "3", "4", "5"], "finalized");
    expect(selection.ids).toEqual([1, 2, 4, 5]);
    expect(selection.skipped).toEqual([3]);
    expect(selection.totals).toEqual([
      { currency: "UZS", amount: "9550000.85", count: 3 },
      { currency: "USD", amount: "410.10", count: 1 },
    ]);
  });

  it("pays nothing in a draft, and nothing whose amount is hidden", () => {
    expect(paySelection([slip(1)], [1], "draft").ids).toEqual([]);
    expect(paySelection([slip(1, { net: undefined })], [1], "finalized")).toMatchObject({ ids: [], skipped: [1] });
  });
});

describe("bulk decisions", () => {
  const rows = [adjustment(1, "proposed"), adjustment(2, "approved"), adjustment(3, "proposed")];

  it("take only proposed rows; approving sends no reason", () => {
    expect(bulkPlan(rows, ["1", "2", "3"], "approve")).toEqual({ ids: [1, 3], skipped: [2], body: { ids: [1, 3], approve: true } });
  });

  it("rejecting sends the reason, trimmed", () => {
    expect(bulkPlan(rows, [3], "reject", "  Wrong month  ").body).toEqual({ ids: [3], approve: false, reason: "Wrong month" });
  });

  it("reads the server's answer: how many were decided, and what it refused", () => {
    const outcome = bulkOutcome([
      { id: 1, ok: true, status: "approved" },
      { id: 3, ok: false, error: "Already decided." },
    ]);
    expect(outcome.decided).toBe(1);
    expect(outcome.refused).toEqual([{ id: 3, ok: false, error: "Already decided." }]);
  });
});

describe("rule builder", () => {
  it("sends a per-unit fine with its free units, amount and cap", () => {
    const draft: RuleDraft = { ...emptyRule("fine"), name: " Late arrivals ", amount: "20000.00", cap: "200000.00", positions: [4, 6] };
    expect(ruleInput(draft)).toEqual({
      name: "Late arrivals",
      kind: "fine",
      metric: "attendance.late_arrivals",
      mode: "per_unit",
      op: "gt",
      threshold: "0",
      free_units: 2,
      tiers: [],
      amount_type: "fixed",
      amount: "20000.00",
      cap: "200000.00",
      min_tasks: 0,
      positions: [4, 6],
      evaluate: "monthly",
      auto_approve: false,
      is_active: false,
    });
  });

  it("a tiered rule sends sorted steps and no threshold, amount or free units", () => {
    const draft: RuleDraft = {
      ...emptyRule("bonus"),
      name: "On time",
      mode: "tiered",
      free_units: 3,
      amount: "100000.00",
      tiers: [
        { from: 98, amount: "400000.00" },
        { from: 95, amount: "200000.00" },
      ],
    };
    const input = ruleInput(draft);
    expect(input).toMatchObject({ mode: "tiered", threshold: null, amount: null, free_units: 0, amount_type: "fixed", min_tasks: 10 });
    expect(input.tiers).toEqual([
      { from: "95", amount: "200000.00" },
      { from: "98", amount: "400000.00" },
    ]);
  });

  it("a sales bonus pays a percent of sales, sent as the amount", () => {
    const draft = adaptToMetric({ ...emptyRule("bonus"), name: "Sales bonus", threshold: 0 }, "sales.net");
    expect(draft).toMatchObject({ amount_type: "percent", mode: "once", op: "gte" });
    expect(ruleProblems(draft)).toEqual(["percent"]);
    const input = ruleInput({ ...draft, percent: 1 });
    expect(input).toMatchObject({ metric: "sales.net", amount_type: "percent", amount: "1", min_tasks: 0, cap: null });
  });

  it("the preview asks for the draft as it would be saved, for a month", () => {
    const draft: RuleDraft = { ...emptyRule("fine"), name: "Late", amount: "20000.00" };
    expect(previewBody(draft, "2026-10-01")).toEqual({ ...ruleInput(draft), period: "2026-10-01" });
  });

  it("says what the form still needs", () => {
    expect(ruleProblems(emptyRule("fine"))).toEqual(["name", "amount"]);
    expect(ruleProblems({ ...emptyRule("bonus"), name: "x", mode: "tiered", tiers: [{ from: 90, amount: null }] })).toEqual(["tiers"]);
    expect(ruleProblems({ ...emptyRule("bonus"), name: "x", threshold: null, amount: "1.00" })).toEqual(["threshold"]);
  });

  it("no per-unit rule on a percentage; a saved rule comes back into the same form", () => {
    expect(adaptToMetric({ ...emptyRule("fine") }, "tasks.on_time_percent").mode).toBe("once");
    const rule: Rule = {
      id: 3,
      ...ruleInput({ ...emptyRule("fine"), name: "Late", amount: "20000.00", positions: [] }),
      positions: [{ id: 4, name: "Farmatsevt" }],
      currency: "UZS",
    };
    expect(ruleToDraft(rule)).toMatchObject({ name: "Late", threshold: 0, amount: "20000.00", percent: null, positions: [4] });
  });
});

describe("pay history and locks", () => {
  const rows = [comp(1, "2026-01-01", { locked: true }), comp(2, "2026-10-01", { amount: "5600000.00", locked: true }), comp(3, "2026-12-01", { amount: "6000000.00" })];

  it("the current setup is the latest that has started; a later one is upcoming", () => {
    const history = payHistory(rows, "2026-11-02");
    expect(history.current?.id).toBe(2);
    expect(history.upcoming?.id).toBe(3);
    expect(history.history.map((row) => row.id)).toEqual([3, 2, 1]);
  });

  it("a change makes a new row, edits an unused one, and can't touch a locked one", () => {
    expect(changePlan(rows, "2027-01-01")).toEqual({ mode: "create" });
    expect(changePlan(rows, "2026-12-01")).toEqual({ mode: "update", id: 3 });
    expect(changePlan(rows, "2026-10-01")).toMatchObject({ mode: "locked", row: { id: 2 } });
    expect(suggestedEffectiveFrom("2026-11-02")).toBe("2026-12-01");
  });

  it("filters the people list: only those without pay, or one pay type", () => {
    const withPay: PayRow = { member: { id: 3, name: "Alisher Valiyev" }, current: rows[1]!, next: rows[2]! };
    const without: PayRow = { member: { id: 9, name: "Aziza Rasulova" }, current: null, next: null };
    expect([withPay, without].filter((row) => payRowMatches(row, { missing: true, type: "all" })).map((row) => row.member.id)).toEqual([9]);
    expect([withPay, without].filter((row) => payRowMatches(row, { missing: false, type: "monthly" })).map((row) => row.member.id)).toEqual([3]);
    expect([withPay, without].filter((row) => payRowMatches(row, { missing: false, type: "hourly" }))).toEqual([]);
  });
});

describe("amounts", () => {
  it("an amount the server left out is hidden, never zero", () => {
    expect(hasAmount(undefined)).toBe(false);
    expect(hasAmount(null)).toBe(false);
    expect(hasAmount("0.00")).toBe(true);
  });

  it("fines show with a minus, the number untouched", () => {
    expect(signedAmount({ kind: "fine", amount: "50000.00" })).toBe("-50000.00");
    expect(signedAmount({ kind: "bonus", amount: "300000.00" })).toBe("300000.00");
    expect(signedAmount({ kind: "deduction", amount: undefined })).toBeUndefined();
    expect(formatMoney(signedAmount({ kind: "fine", amount: "50000.00" }), "UZS", "uz")).toBe("−50\u00a0000\u00a0so‘m");
  });

  it("money from the API is shown exactly, in each language", () => {
    expect(formatMoney("4960000.00", "UZS", "uz")).toBe("4\u00a0960\u00a0000\u00a0so‘m");
    expect(formatMoney("4960000.50", "UZS", "ru")).toBe("4\u00a0960\u00a0000,50\u00a0сум");
    expect(formatMoney("4960000.00", "UZS", "en")).toBe("4,960,000\u00a0UZS");
  });

  it("repaid share comes from the server's amounts", () => {
    expect(repaidShare({ amount: "1000000.00", repaid: "500000.00" })).toBe(50);
    expect(repaidShare({ amount: undefined, repaid: "500000.00" })).toBeNull();
  });
});

describe("runs and months", () => {
  it("suggests last month while neither it nor this month has a run, else this month", () => {
    expect(prepareTarget([], "2026-11-02")).toBe("2026-10-01");
    expect(prepareTarget([run({ period: "2026-10-01", status: "paid" })], "2026-11-02")).toBe("2026-11-01");
    expect(prepareTarget([run({ period: "2026-10-01" }), run({ period: "2026-11-01" })], "2026-11-02")).toBeNull();
    expect(prepareTarget([run({ period: "2026-10-01", status: "cancelled" })], "2026-11-02")).toBe("2026-10-01");
  });

  it("names the month alone in each language", () => {
    expect(monthName("2026-11-01", "uz")).toBe("Noyabr");
    expect(monthName("2026-11-01", "en")).toBe("November");
    expect(monthName("2026-11-01", "ru")).toBe("ноябрь");
  });

  it("links each warning to where it is fixed", () => {
    expect(warningLink({ code: "no_compensation", message: "", member: { id: 12, name: "A" } })).toBe("payroll/pay?member=12");
    expect(warningLink({ code: "disputes_open", message: "" })).toBe("payroll/adjustments?tab=disputed");
    expect(warningLink({ code: "something_new", message: "" })).toBeNull();
  });
});

describe("payslip lines", () => {
  const line = (id: number, kind: PayslipLine["kind"], amount: string, order: number, extra: Partial<PayslipLine> = {}): PayslipLine => ({
    id,
    kind,
    label: kind,
    params: {},
    quantity: null,
    rate: null,
    amount,
    adjustment: null,
    advance: null,
    order,
    ...extra,
  });

  it("groups what is earned, what is taken and the rounding, in order", () => {
    const groups = lineGroups([line(3, "fine", "-50000.00", 3), line(1, "base", "4800000.00", 1), line(4, "rounding", "-500.00", 9), line(2, "manual", "-10000.00", 2), line(5, "night_work", "400000.00", 4)]);
    expect(groups.earnings.map((row) => row.id)).toEqual([1, 5]);
    expect(groups.deductions.map((row) => row.id)).toEqual([2, 3]);
    expect(groups.other.map((row) => row.id)).toEqual([4]);
  });

  it("says how a line was worked out when the server sent quantity and rate", () => {
    expect(lineHow(line(1, "base", "4800000.00", 1, { quantity: "24.0", rate: "200000.00" }))).toEqual({ quantity: "24.0", rate: "200000.00" });
    expect(lineHow(line(1, "bonus", "300000.00", 1))).toBeNull();
    expect(quantityText("24.0", "uz")).toBe("24");
    expect(quantityText("1.50", "ru")).toBe("1,5");
    expect(quantityText("1.50", "en")).toBe("1.5");
  });
});

describe("payout accounts", () => {
  it("lists accounts in the currency, the ones that suit the method first", () => {
    const accounts: PayAccount[] = [
      { id: 1, name: "Bank Kapital", kind: "bank", currency: "UZS" },
      { id: 2, name: "Kassa Chilonzor", kind: "cash", currency: "UZS" },
      { id: 3, name: "Dollar kassa", kind: "cash", currency: "USD" },
    ];
    expect(accountsFor(accounts, "UZS", "cash").map((a) => a.id)).toEqual([2, 1]);
    expect(accountsFor(accounts, "UZS", "bank").map((a) => a.id)).toEqual([1, 2]);
    expect(accountsFor(accounts, "USD", "card").map((a) => a.id)).toEqual([3]);
  });
});

describe("settings", () => {
  const settings: PayrollSettings = {
    currency: "UZS",
    pay_day: 5,
    advance_day: 20,
    advance_cap_percent: 50,
    amounts_are_net: true,
    taxes_enabled: false,
    income_tax_percent: "12.00",
    social_tax_percent: "12.00",
    inps_percent: "0.10",
    deductions_cap_percent: "20.00",
    rounding_step: "1000.00",
    overtime_multiplier: "2.00",
    holiday_work_multiplier: "2.00",
    night_multiplier: "1.50",
    night_starts_at: "22:00:00",
    night_ends_at: "06:00:00",
    daily_hours: "8.00",
    auto_prepare: true,
  };

  it("sends only what changed, decimals as strings and times as HH:MM", () => {
    const form = settingsForm(settings);
    expect(settingsChanges(settings, form)).toEqual({});
    form.night_multiplier = 1.75;
    form.night_starts_at = "21:00";
    form.advance_day = null;
    form.taxes_enabled = true;
    expect(settingsChanges(settings, form)).toEqual({ night_multiplier: "1.75", night_starts_at: "21:00", advance_day: null, taxes_enabled: true });
  });
});
